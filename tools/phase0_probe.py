#!/usr/bin/env python3
"""
CompetitorTrack — Phase 0 validation probe.

Purpose
-------
Prove (or disprove) that the public Shopify storefront JSON endpoint is usable
FROM THE MACHINE THAT WILL RUN PRODUCTION. Reputation-based blocking is
IP-specific, so results are only meaningful when this script is executed on the
production server. Running it anywhere else produces a *control* measurement,
never the verdict.

This script writes NO application code and touches no database. It only reads
public endpoints and records exactly what it observed.

Usage
-----
    python3 tools/phase0_probe.py --stores stores.txt --ua browser \
        --out phase0_results.json --fixtures-dir tests/fixtures/phase0

    # second pass with the honest bot UA, after a gap (see README_PHASE0.md)
    python3 tools/phase0_probe.py --stores stores.txt --ua bot \
        --bot-ua-origin https://app.example.com --out phase0_results_bot.json

    # through a proxy (only if one is configured) — enables the geo-price diff
    python3 tools/phase0_probe.py --stores stores.txt --ua browser \
        --proxy socks5h://user:pass@host:1080 --out phase0_results_proxy.json

    # cheap pre-screen: robots + meta + limit=1 only
    python3 tools/phase0_probe.py --stores stores.txt --quick --out prescreen.json

Design notes
------------
* One transport per invocation (direct OR proxy), mirroring the production
  invariant "one run = one transport". Mixing transports inside one pass could
  mix geo-localised prices and make the direct-vs-proxy diff meaningless.
* `trust_env=False` so an ambient HTTP_PROXY on the host can never silently
  change egress.
* `follow_redirects=False`; redirects are classified by us, exactly as the
  production classifier does.
* Requests to one domain are strictly sequential with POLITE delay + jitter.
* Proxy credentials are redacted to scheme://host:port everywhere in the output.
* Runs on Python 3.9+ and on 3.12 (the production target). No 3.10-only syntax,
  so the script can be validated in a 3.9 sandbox before it is handed over.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import re
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "ERROR: httpx is not installed.\n"
        "  python3 -m venv .venv && . .venv/bin/activate && pip install 'httpx[socks]'\n"
    )
    raise SystemExit(2)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SCHEMA = "competitortrack.phase0/1"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
BOT_UA_TEMPLATE = "CompetitorTrackBot/1.0 (+{origin}/bot)"

# Headers worth recording verbatim: they identify the CDN/WAF in front of the
# store and carry the rate-limit signals we need to reason about.
INTERESTING_HEADERS = (
    "server",
    "powered-by",
    "x-shopid",
    "x-sorting-hat-shopid",
    "x-shardid",
    "content-type",
    "retry-after",
    "cf-ray",
    "cf-cache-status",
    "cf-mitigated",
    "server-timing",
    "x-request-id",
    "x-frame-options",
)

# Two-label public suffixes we care about, so "shop.co.uk" is not reduced to
# "co.uk". Heuristic on purpose: a probe does not need the full PSL.
TWO_LABEL_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "me.uk", "ac.uk", "gov.uk", "co.nz", "co.za",
        "com.au", "net.au", "org.au", "com.br", "com.mx", "co.jp", "co.kr",
        "co.in", "com.tr", "com.sg", "com.hk", "com.pk",
    }
)

# Per A6.3. Only a 200 carrying parseable JSON with a "products" array is usable.
ERR_ENDPOINT_DISABLED = "endpoint_disabled"
ERR_PASSWORD_PROTECTED = "password_protected"
ERR_REDIRECTED_AWAY = "redirected_away"
ERR_UNAVAILABLE = "unavailable"
ERR_BLOCKED = "blocked"
ERR_RATE_LIMITED = "rate_limited"
ERR_NETWORK = "network"
ERR_PARSE = "parse"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(domain: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")


def redact_proxy(url: Optional[str]) -> Optional[str]:
    """Return scheme://host:port — never the credentials."""
    if not url:
        return None
    parts = urlsplit(url)
    host = parts.hostname or "?"
    port = ":%d" % parts.port if parts.port else ""
    creds = " (credentials redacted)" if parts.username else ""
    return "%s://%s%s%s" % (parts.scheme, host, port, creds)


def registrable_domain(host: str) -> str:
    labels = host.lower().strip(".").split(".")
    if len(labels) < 2:
        return host.lower()
    last_two = ".".join(labels[-2:])
    if last_two in TWO_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def normalize_domain(raw: str) -> str:
    """Accept a full URL or a bare host; return the lowercase host only."""
    raw = raw.strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = urlsplit(raw).hostname or ""
    return host.lower()


def pct(part: int, whole: int) -> Optional[float]:
    if not whole:
        return None
    return round(part * 100.0 / whole, 2)


async def polite_sleep(delay: float) -> None:
    """POLITE_DELAY_SECONDS with +/-30% jitter, as production does."""
    if delay <= 0:
        return
    await asyncio.sleep(delay * random.uniform(0.7, 1.3))


def picked_headers(headers: Any) -> Dict[str, str]:
    out = {}
    for name in INTERESTING_HEADERS:
        value = headers.get(name)
        if value is not None:
            out[name] = value
    return out


# --------------------------------------------------------------------------- #
# Response classification (mirrors A6.3)
# --------------------------------------------------------------------------- #


def classify(
    status: int,
    headers: Any,
    body_text: str,
    origin_host: str,
    expect: str = "feed",
) -> Tuple[str, Optional[str], Optional[Any]]:
    """
    Return (outcome, error_code, parsed_json).

    outcome is one of: ok | redirect_same_domain | error

    `expect` selects the success contract for the endpoint being read. The
    product-feed contract ("200 + JSON + a products array") must NOT be applied
    to /robots.txt (text/plain) or /meta.json (JSON with no products key) —
    doing so labels perfectly good 200 responses as endpoint_disabled and makes
    the results file read as if every store had failed:
        feed -> 200 + parseable JSON + a "products" key
        json -> 200 + parseable JSON of any shape
        text -> 200 with a body
    """
    location = headers.get("location") or ""

    if status == 200:
        if expect == "text":
            if not body_text:
                return "error", ERR_PARSE, None
            return "ok", None, None
        try:
            parsed = json.loads(body_text)
        except (ValueError, TypeError):
            return "error", ERR_ENDPOINT_DISABLED, None
        if expect == "json":
            return "ok", None, parsed
        if not isinstance(parsed, dict) or "products" not in parsed:
            # A JSON body that is not the product feed shape is equally unusable.
            return "error", ERR_ENDPOINT_DISABLED, None
        return "ok", None, parsed

    if status in (301, 302, 303, 307, 308):
        loc_parts = urlsplit(location)
        loc_path = loc_parts.path or ""
        if loc_path.startswith("/password"):
            return "error", ERR_PASSWORD_PROTECTED, None
        loc_host = (loc_parts.hostname or origin_host).lower()
        if registrable_domain(loc_host) == registrable_domain(origin_host):
            return "redirect_same_domain", None, None
        return "error", ERR_REDIRECTED_AWAY, None

    if status == 401:
        return "error", ERR_PASSWORD_PROTECTED, None
    if status == 402:
        return "error", ERR_UNAVAILABLE, None
    if status in (403, 430):
        return "error", ERR_BLOCKED, None
    if status == 404:
        return "error", ERR_ENDPOINT_DISABLED, None
    if status == 429:
        return "error", ERR_RATE_LIMITED, None
    if status >= 500:
        return "error", ERR_NETWORK, None
    return "error", "http_%d" % status, None


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #


async def fetch(
    client: "httpx.AsyncClient",
    url: str,
    delay: float,
    max_hops: int = 2,
    expect: str = "feed",
) -> Dict[str, Any]:
    """
    GET `url`, classifying redirects ourselves. Returns a record that is safe to
    serialise: no response body, only shape and metadata.
    """
    origin_host = urlsplit(url).hostname or ""
    hops: List[Dict[str, Any]] = []
    current = url
    body_text = ""
    record: Dict[str, Any] = {
        "requested_url": url,
        "final_url": None,
        "status": None,
        "outcome": None,
        "error_code": None,
        "elapsed_ms": None,
        "headers": {},
        "redirect_hops": hops,
        "body_bytes": None,
    }

    for hop_index in range(max_hops + 1):
        started = time.monotonic()
        try:
            resp = await client.get(current)
        except httpx.HTTPError as exc:
            record["final_url"] = current
            record["outcome"] = "error"
            record["error_code"] = ERR_NETWORK
            record["exception"] = type(exc).__name__
            record["exception_detail"] = str(exc)[:300]
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return record

        elapsed_ms = int((time.monotonic() - started) * 1000)
        body_text = resp.text
        record["status"] = resp.status_code
        record["elapsed_ms"] = elapsed_ms
        record["headers"] = picked_headers(resp.headers)
        record["body_bytes"] = len(resp.content)
        record["final_url"] = current

        outcome, error_code, parsed = classify(
            resp.status_code, resp.headers, body_text, origin_host, expect
        )

        if outcome == "redirect_same_domain" and hop_index < max_hops:
            location = resp.headers.get("location") or ""
            hops.append(
                {
                    "from": current,
                    "status": resp.status_code,
                    "location": location,
                }
            )
            current = str(httpx.URL(current).join(location))
            await polite_sleep(delay)
            continue

        if outcome == "redirect_same_domain":
            record["outcome"] = "error"
            record["error_code"] = "too_many_redirects"
            return record

        record["outcome"] = outcome
        record["error_code"] = error_code
        record["_parsed"] = parsed
        record["_body_text"] = body_text
        return record

    return record


# --------------------------------------------------------------------------- #
# Product feed analysis
# --------------------------------------------------------------------------- #


def summarize_products(products: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Field-availability statistics. These decide real engine behaviour:
      * `available` population rate  -> stores.stock_tracking_enabled
      * `inventory_quantity` presence -> confirms it must never be a trigger input
      * price value type             -> confirms decimal-string parsing
    """
    n_variants = 0
    available_present = 0
    compare_at_non_null = 0
    compare_at_key_present = 0
    inventory_qty_present = 0
    variant_updated_at_present = 0
    price_parse_ok = 0
    price_parse_fail = 0
    zero_price_variants = 0
    price_value_types: Dict[str, int] = {}
    product_ids: List[int] = []
    image_present = 0
    published_at_present = 0
    product_updated_at_present = 0
    price_fingerprint: Dict[str, str] = {}
    currencies_seen: Dict[str, int] = {}

    for product in products:
        pid = product.get("id")
        if isinstance(pid, int):
            product_ids.append(pid)
        images = product.get("images") or []
        if images and isinstance(images, list) and (images[0] or {}).get("src"):
            image_present += 1
        if product.get("published_at"):
            published_at_present += 1
        if product.get("updated_at"):
            product_updated_at_present += 1

        for variant in product.get("variants") or []:
            n_variants += 1
            if "available" in variant:
                available_present += 1
            if "compare_at_price" in variant:
                compare_at_key_present += 1
            cap = variant.get("compare_at_price")
            if cap not in (None, "", "0", "0.0", "0.00"):
                compare_at_non_null += 1
            if "inventory_quantity" in variant:
                inventory_qty_present += 1
            if variant.get("updated_at"):
                variant_updated_at_present += 1

            raw_price = variant.get("price")
            type_name = type(raw_price).__name__
            price_value_types[type_name] = price_value_types.get(type_name, 0) + 1
            try:
                value = Decimal(str(raw_price))
            except (InvalidOperation, TypeError, ValueError):
                price_parse_fail += 1
            else:
                price_parse_ok += 1
                if value == 0:
                    zero_price_variants += 1
                vid = variant.get("id")
                if vid is not None:
                    price_fingerprint[str(vid)] = str(raw_price)

            # Some themes expose a per-variant currency; record if so.
            cur = variant.get("currency") or variant.get("price_currency")
            if isinstance(cur, str) and cur:
                currencies_seen[cur] = currencies_seen.get(cur, 0) + 1

    return {
        "n_products": len(products),
        "n_variants": n_variants,
        "product_ids_sample": product_ids[:5],
        "product_ids_count": len(product_ids),
        "available_key_present_pct": pct(available_present, n_variants),
        "compare_at_key_present_pct": pct(compare_at_key_present, n_variants),
        "compare_at_non_null_pct": pct(compare_at_non_null, n_variants),
        "inventory_quantity_present_pct": pct(inventory_qty_present, n_variants),
        "variant_updated_at_present_pct": pct(variant_updated_at_present, n_variants),
        "product_image_present_pct": pct(image_present, len(products)),
        "product_published_at_present_pct": pct(published_at_present, len(products)),
        "product_updated_at_present_pct": pct(product_updated_at_present, len(products)),
        "price_parse_ok": price_parse_ok,
        "price_parse_fail": price_parse_fail,
        "price_parse_fail_pct": pct(price_parse_fail, n_variants),
        "zero_price_variants": zero_price_variants,
        "price_value_types": price_value_types,
        "variant_currency_field_seen": currencies_seen or None,
        "_price_fingerprint": price_fingerprint,
    }


# --------------------------------------------------------------------------- #
# robots.txt
# --------------------------------------------------------------------------- #


def robots_agent_token(user_agent: str) -> str:
    """
    urllib.robotparser matches on `useragent.split('/')[0].lower()`, so a full
    browser UA is evaluated as the agent token "mozilla" and our bot UA as
    "competitortrackbot". Recording the token makes the verdict auditable
    instead of mysterious.
    """
    return user_agent.split("/")[0].strip().lower()


def evaluate_robots(
    robots_text: str, user_agent: str, paths: List[str]
) -> Dict[str, Any]:
    parser = RobotFileParser()
    parser.parse(robots_text.splitlines())
    verdicts = {}
    for path in paths:
        try:
            verdicts[path] = bool(parser.can_fetch(user_agent, path))
        except Exception as exc:  # defensive: malformed robots.txt
            verdicts[path] = None
            verdicts[path + "__error"] = type(exc).__name__
    return {
        "agent_token_used": robots_agent_token(user_agent),
        "crawl_delay": parser.crawl_delay(user_agent),
        "request_rate": str(parser.request_rate(user_agent) or ""),
        "allows": verdicts,
        "mentions_products_json": "products.json" in robots_text,
        "n_lines": len(robots_text.splitlines()),
    }


# --------------------------------------------------------------------------- #
# Egress identity & SMTP reachability
# --------------------------------------------------------------------------- #


async def egress_identity(client: "httpx.AsyncClient") -> Dict[str, Any]:
    """Public IP, reverse DNS and ASN of whatever path this pass is using."""
    result: Dict[str, Any] = {"ip": None, "reverse_dns": None, "ipinfo": None}
    try:
        resp = await client.get("https://api.ipify.org?format=json")
        if resp.status_code == 200:
            result["ip"] = (resp.json() or {}).get("ip")
    except Exception as exc:
        result["ipify_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])

    if result["ip"]:
        try:
            result["reverse_dns"] = socket.gethostbyaddr(result["ip"])[0]
        except Exception:
            result["reverse_dns"] = None

    try:
        resp = await client.get("https://ipinfo.io/json")
        if resp.status_code == 200:
            info = resp.json() or {}
            result["ipinfo"] = {
                k: info.get(k)
                for k in ("ip", "hostname", "city", "region", "country", "org", "timezone")
            }
    except Exception as exc:
        result["ipinfo_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])

    return result


def smtp_probe(host: str, port: int, timeout: float = 12.0) -> Dict[str, Any]:
    """
    TCP + TLS reachability only. Nothing is authenticated and no mail is sent.
    Oracle Cloud blocks outbound port 25 permanently; 587/465 are expected to
    work, and this is where that expectation gets tested rather than assumed.
    """
    out: Dict[str, Any] = {
        "host": host,
        "port": port,
        "tcp_connect": False,
        "banner": None,
        "tls": None,
        "tls_version": None,
        "error": None,
    }
    sock = None
    try:
        started = time.monotonic()
        sock = socket.create_connection((host, port), timeout=timeout)
        out["tcp_connect"] = True
        out["connect_ms"] = int((time.monotonic() - started) * 1000)
        sock.settimeout(timeout)
        context = ssl.create_default_context()

        if port == 465:
            wrapped = context.wrap_socket(sock, server_hostname=host)
            sock = wrapped
            out["banner"] = sock.recv(512).decode("utf-8", "replace").strip()[:200]
            out["tls"] = "implicit"
            out["tls_version"] = sock.version()
        else:
            out["banner"] = sock.recv(512).decode("utf-8", "replace").strip()[:200]
            sock.sendall(b"EHLO competitortrack.probe\r\n")
            ehlo = sock.recv(2048).decode("utf-8", "replace")
            out["starttls_advertised"] = "STARTTLS" in ehlo.upper()
            if out["starttls_advertised"]:
                sock.sendall(b"STARTTLS\r\n")
                reply = sock.recv(512).decode("utf-8", "replace").strip()
                out["starttls_reply"] = reply[:120]
                if reply.startswith("220"):
                    wrapped = context.wrap_socket(sock, server_hostname=host)
                    sock = wrapped
                    out["tls"] = "starttls"
                    out["tls_version"] = sock.version()
        try:
            sock.sendall(b"QUIT\r\n")
        except OSError:
            pass
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # A real SMTP server opens with a "220" greeting. A TCP connect that
    # succeeds without one means something local accepted the socket and then
    # dropped it (egress firewall, transparent proxy) — that is NOT evidence
    # the port is reachable, and reporting it as success would be a lie.
    banner = out.get("banner") or ""
    if out["tcp_connect"] and banner.startswith("220") and out.get("tls"):
        out["conclusive"] = True
        out["assessment"] = "reachable — TLS established after a valid 220 greeting"
    elif out["tcp_connect"] and not banner:
        out["conclusive"] = False
        out["assessment"] = (
            "INCONCLUSIVE — TCP accepted but no SMTP greeting arrived. Typical of "
            "an egress firewall that permits only HTTP/HTTPS. Re-run on the "
            "production server; do not treat this as a pass or a fail."
        )
    elif not out["tcp_connect"]:
        out["conclusive"] = True
        out["assessment"] = "BLOCKED — TCP connect failed: %s" % out.get("error")
    else:
        out["conclusive"] = False
        out["assessment"] = (
            "INCONCLUSIVE — greeting=%r, tls=%s, error=%s"
            % (banner[:40], out.get("tls"), out.get("error"))
        )
    return out


# --------------------------------------------------------------------------- #
# Per-store probe
# --------------------------------------------------------------------------- #


def feed_path(collection_handle: str) -> str:
    if collection_handle:
        return "/collections/%s/products.json" % collection_handle
    return "/products.json"


def write_fixture(
    fixtures_dir: Optional[str], domain: str, name: str, content: str
) -> Optional[str]:
    if not fixtures_dir or content is None:
        return None
    target_dir = os.path.join(fixtures_dir, slugify(domain))
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


async def probe_store(
    client: "httpx.AsyncClient",
    domain: str,
    collection_handle: str,
    tier: str,
    user_agent: str,
    delay: float,
    quick: bool,
    max_pages: int,
    fixtures_dir: Optional[str],
    fixtures_max_pages: int,
) -> Dict[str, Any]:
    base = "https://%s" % domain
    path = feed_path(collection_handle)
    store: Dict[str, Any] = {
        "domain": domain,
        "collection_handle": collection_handle or "",
        "tier": tier,
        "feed_path": path,
        "probed_at": utc_now_iso(),
        "robots": None,
        "meta": None,
        "limit1": None,
        "pages": {},
        "since_id_probe": None,
        "www_variant": None,
        "field_stats": None,
        "page_repeat_detected": None,
        "verdict": None,
        "notes": [],
    }

    # --- robots.txt -------------------------------------------------------- #
    robots_rec = await fetch(client, base + "/robots.txt", delay, expect="text")
    robots_text = robots_rec.pop("_body_text", "") or ""
    robots_rec.pop("_parsed", None)
    store["robots"] = {"fetch": robots_rec}
    robots_status = robots_rec.get("status")

    if robots_status == 200 and robots_text:
        paths = [path, "/products.json"]
        if collection_handle:
            paths.append("/collections/%s" % collection_handle)
        store["robots"]["policy"] = "rules_read"
        store["robots"]["evaluation"] = evaluate_robots(robots_text, user_agent, paths)
        write_fixture(fixtures_dir, domain, "robots.txt", robots_text)
        if store["robots"]["evaluation"]["allows"].get(path) is False:
            store["verdict"] = "robots_disallowed"
            store["notes"].append(
                "robots.txt DISALLOWS the feed path for agent token "
                + store["robots"]["evaluation"]["agent_token_used"]
                + " — this store must be EXCLUDED from the Phase 0 set (P0 task 2)."
            )
            return store
    elif robots_status is not None and 400 <= robots_status < 500:
        # RFC 9309: a 4xx means "no restrictions stated"; urllib.robotparser
        # sets allow_all on 4xx. Safe to proceed.
        store["robots"]["policy"] = "absent_4xx_allow_all"
        store["notes"].append(
            "robots.txt returned %d — no rules stated, crawling the feed is "
            "permitted (RFC 9309)." % robots_status
        )
    else:
        # 5xx or a transport failure. RFC 9309 / robotparser treat an
        # unreachable robots.txt as DISALLOW-ALL, so we must not claim consent.
        # The probe still measures the feed (diagnosis is the point), but the
        # store is not admissible to the Phase 0 set until robots is readable.
        store["robots"]["policy"] = "unreadable_conservative_disallow"
        store["robots"]["admissible"] = False
        store["notes"].append(
            "robots.txt UNREADABLE (status=%s, error=%s). Per RFC 9309 an "
            "unreachable robots.txt means disallow-all, so consent is NOT "
            "established. Feed measurements below are diagnostic only; this "
            "store cannot enter the Phase 0 set until robots.txt is readable."
            % (robots_status, robots_rec.get("error_code"))
        )

    await polite_sleep(delay)

    # --- /meta.json -------------------------------------------------------- #
    meta_rec = await fetch(client, base + "/meta.json", delay, expect="json")
    meta_body = meta_rec.pop("_body_text", "") or ""
    meta_parsed = meta_rec.pop("_parsed", None)
    meta_json: Optional[Dict[str, Any]] = None
    if meta_rec.get("status") == 200 and meta_body:
        try:
            meta_json = json.loads(meta_body)
        except ValueError:
            meta_json = None
        write_fixture(fixtures_dir, domain, "meta.json", meta_body)
    headers = meta_rec.get("headers") or {}
    store["meta"] = {
        "fetch": meta_rec,
        "currency": (meta_json or {}).get("currency"),
        "shop_name": (meta_json or {}).get("name"),
        "country": (meta_json or {}).get("country"),
        "is_shopify_by_header": bool(
            headers.get("powered-by")
            or headers.get("x-shopid")
            or headers.get("x-sorting-hat-shopid")
        ),
        "keys": sorted((meta_json or {}).keys()) if isinstance(meta_json, dict) else None,
    }
    if not store["meta"]["is_shopify_by_header"]:
        store["notes"].append(
            "No powered-by/x-shopid header on /meta.json — production add-store "
            "validation would reject this as not_shopify. Verify before using."
        )

    await polite_sleep(delay)

    # --- feed, limit=1 ----------------------------------------------------- #
    limit1 = await fetch(client, base + path + "?limit=1", delay)
    limit1_body = limit1.pop("_body_text", "") or ""
    limit1_parsed = limit1.pop("_parsed", None)
    if limit1.get("outcome") == "ok" and limit1_body:
        write_fixture(fixtures_dir, domain, "products_limit1.json", limit1_body)
    store["limit1"] = {
        "fetch": limit1,
        "n_products": len((limit1_parsed or {}).get("products") or [])
        if limit1_parsed
        else None,
    }

    if limit1.get("outcome") != "ok":
        store["verdict"] = "blocked_or_unusable"
        store["notes"].append(
            "Feed not usable on the cheapest possible request (limit=1): "
            "error_code=%s, status=%s. This is the decisive datapoint for this store."
            % (limit1.get("error_code"), limit1.get("status"))
        )
        return store

    if quick:
        store["verdict"] = "feed_ok_prescreen"
        return store

    await polite_sleep(delay)

    # --- pagination -------------------------------------------------------- #
    previous_ids: Optional[List[int]] = None
    # Anchor for the since_id probe must come from the last NON-EMPTY page.
    # Tracking "the last page seen" instead would leave it empty for every
    # store whose catalog ends on an empty page — i.e. every healthy small
    # store — and silently skip the probe P0 requires for all of them.
    anchor_products: List[Dict[str, Any]] = []
    all_stats: Optional[Dict[str, Any]] = None
    pages_fetched = 0
    ended_on_empty_page = False
    last_page_was_full = False

    for page in range(1, max_pages + 1):
        url = "%s%s?limit=250&page=%d" % (base, path, page)
        rec = await fetch(client, url, delay)
        body = rec.pop("_body_text", "") or ""
        parsed = rec.pop("_parsed", None)
        page_entry: Dict[str, Any] = {"fetch": rec}

        if rec.get("outcome") == "ok" and parsed is not None:
            products = parsed.get("products") or []
            page_entry["n_products"] = len(products)
            stats = summarize_products(products)
            fingerprint = stats.pop("_price_fingerprint")
            page_entry["stats"] = stats
            if page == 1:
                all_stats = stats
                store["_page1_price_fingerprint"] = fingerprint
            if body and page <= fixtures_max_pages:
                write_fixture(fixtures_dir, domain, "page%d.json" % page, body)

            current_ids = sorted(
                p.get("id") for p in products if isinstance(p.get("id"), int)
            )
            if previous_ids is not None and current_ids and current_ids == previous_ids:
                store["page_repeat_detected"] = page
                page_entry["page_repeat"] = True
                store["pages"]["page%d" % page] = page_entry
                store["notes"].append(
                    "PAGE-REPEAT at page %d: identical product-ID set as page %d. "
                    "Production treats this as a partial run with exceeds_cap=true."
                    % (page, page - 1)
                )
                break
            previous_ids = current_ids
            pages_fetched = page
            last_page_was_full = len(products) >= 250
            if products:
                anchor_products = products

            if not products:
                page_entry["empty_page"] = True
                ended_on_empty_page = True
                store["pages"]["page%d" % page] = page_entry
                store["notes"].append(
                    "Catalog ended with an empty products array at page %d "
                    "(a COMPLETE run in production terms)." % page
                )
                break
        else:
            page_entry["n_products"] = None
            store["pages"]["page%d" % page] = page_entry
            store["notes"].append(
                "Page %d failed: error_code=%s, status=%s."
                % (page, rec.get("error_code"), rec.get("status"))
            )
            break

        store["pages"]["page%d" % page] = page_entry
        await polite_sleep(delay)

    store["field_stats"] = all_stats

    # --- completeness, per A6.4 ------------------------------------------- #
    total_products = sum(
        (entry.get("n_products") or 0) for entry in store["pages"].values()
    )
    if store.get("page_repeat_detected"):
        completeness = "partial_page_repeat"
    elif ended_on_empty_page:
        completeness = "complete"
    elif pages_fetched >= max_pages and last_page_was_full:
        completeness = "partial_cap_exceeded"
        store["notes"].append(
            "CAP EXCEEDED: %d pages x 250 fetched with a still-full last page, "
            "so the catalog is larger than max_pages*250=%d. Production marks "
            "this run PARTIAL with error_code=cap_exceeded and sets "
            "stores.exceeds_cap=true, which means it NEVER completes a baseline "
            "and emits NO variant/product alerts until a collection is picked. "
            "This store needs collection scoping to be trackable."
            % (pages_fetched, max_pages * 250)
        )
    else:
        completeness = "indeterminate"

    store["pagination"] = {
        "pages_fetched": pages_fetched,
        "total_products_seen": total_products,
        "ended_on_empty_page": ended_on_empty_page,
        "last_page_was_full": last_page_was_full,
        "page_repeat_at": store.get("page_repeat_detected"),
        "completeness": completeness,
        "exceeds_cap": completeness == "partial_cap_exceeded"
        or bool(store.get("page_repeat_detected")),
    }

    # --- since_id probe (expected to be IGNORED by the storefront feed) ---- #
    if anchor_products:
        anchor = None
        for product in anchor_products:
            if isinstance(product.get("id"), int):
                anchor = product["id"]
        if anchor is not None:
            await polite_sleep(delay)
            url = "%s%s?limit=250&since_id=%d" % (base, path, anchor)
            rec = await fetch(client, url, delay)
            body = rec.pop("_body_text", "") or ""
            parsed = rec.pop("_parsed", None)
            first_ids = []
            if parsed:
                first_ids = [
                    p.get("id") for p in (parsed.get("products") or [])[:5]
                ]
            page1 = store["pages"].get("page1", {})
            page1_sample = ((page1.get("stats") or {}).get("product_ids_sample")) or []
            store["since_id_probe"] = {
                "fetch": rec,
                "anchor_id": anchor,
                "first_ids": first_ids,
                "identical_to_page1_head": bool(
                    first_ids and page1_sample and first_ids == page1_sample
                ),
                "interpretation": (
                    "IGNORED (same head as page 1) — confirms no cursor pagination"
                    if first_ids and page1_sample and first_ids == page1_sample
                    else "DIFFERENT head — since_id may be honoured; re-read A6.4 "
                    "before relying on page=N"
                ),
            }

    # --- www / apex redirect behaviour ------------------------------------- #
    other_host = (
        domain[4:] if domain.startswith("www.") else "www." + domain
    )
    await polite_sleep(delay)
    alt = await fetch(client, "https://%s%s?limit=1" % (other_host, path), delay)
    alt.pop("_body_text", None)
    alt.pop("_parsed", None)
    store["www_variant"] = {"host_tried": other_host, "fetch": alt}

    store["verdict"] = "feed_ok"
    return store


# --------------------------------------------------------------------------- #
# Store list parsing
# --------------------------------------------------------------------------- #


def parse_store_list(path: str) -> List[Tuple[str, str, str]]:
    """
    One store per line:
        domain.com
        domain.com  collection-handle
        domain.com  collection-handle  # tier:large
    `#` starts a comment. A `tier:` token in the comment is recorded.
    """
    entries: List[Tuple[str, str, str]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            tier = ""
            if "#" in raw_line:
                raw_line, comment = raw_line.split("#", 1)
                match = re.search(r"tier:(\S+)", comment)
                if match:
                    tier = match.group(1)
            tokens = raw_line.split()
            if not tokens:
                continue
            domain = normalize_domain(tokens[0])
            if not domain:
                continue
            collection = tokens[1] if len(tokens) > 1 else ""
            entries.append((domain, collection, tier))
    return entries


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #


def build_summary(stores: List[Dict[str, Any]]) -> Dict[str, Any]:
    usable = [s for s in stores if s.get("verdict") in ("feed_ok", "feed_ok_prescreen")]
    blocked = [
        s
        for s in stores
        if (s.get("limit1") or {}).get("fetch", {}).get("error_code") == ERR_BLOCKED
    ]
    rate_limited = [
        s
        for s in stores
        if (s.get("limit1") or {}).get("fetch", {}).get("error_code") == ERR_RATE_LIMITED
    ]
    robots_excluded = [s for s in stores if s.get("verdict") == "robots_disallowed"]
    robots_unreadable = [
        s for s in stores if (s.get("robots") or {}).get("admissible") is False
    ]
    # Only stores with BOTH a usable feed and established robots consent count.
    admissible = [s for s in usable if (s.get("robots") or {}).get("admissible") is not False]

    avail_rates = [
        (s.get("field_stats") or {}).get("available_key_present_pct")
        for s in stores
        if s.get("field_stats")
    ]
    avail_rates = [r for r in avail_rates if r is not None]
    inv_rates = [
        (s.get("field_stats") or {}).get("inventory_quantity_present_pct")
        for s in stores
        if s.get("field_stats")
    ]
    inv_rates = [r for r in inv_rates if r is not None]

    return {
        "n_stores_probed": len(stores),
        "n_feed_ok": len(usable),
        "n_blocked_403_430": len(blocked),
        "n_rate_limited_429": len(rate_limited),
        "n_robots_disallowed": len(robots_excluded),
        "domains_feed_ok": [s["domain"] for s in usable],
        "domains_blocked": [s["domain"] for s in blocked],
        "domains_rate_limited": [s["domain"] for s in rate_limited],
        "domains_robots_disallowed": [s["domain"] for s in robots_excluded],
        "available_key_pct_min": min(avail_rates) if avail_rates else None,
        "available_key_pct_max": max(avail_rates) if avail_rates else None,
        "inventory_quantity_pct_min": min(inv_rates) if inv_rates else None,
        "inventory_quantity_pct_max": max(inv_rates) if inv_rates else None,
        "page_repeat_domains": [
            s["domain"] for s in stores if s.get("page_repeat_detected")
        ],
        "n_admissible_feed_ok_and_robots_consent": len(admissible),
        "domains_robots_unreadable": [s["domain"] for s in robots_unreadable],
        "domains_exceeds_cap": [
            s["domain"]
            for s in stores
            if (s.get("pagination") or {}).get("exceeds_cap")
        ],
        "domains_complete_catalog": [
            s["domain"]
            for s in stores
            if (s.get("pagination") or {}).get("completeness") == "complete"
        ],
        "inventory_quantity_exposed_anywhere": any(
            ((s.get("field_stats") or {}).get("inventory_quantity_present_pct") or 0) > 0
            for s in stores
        ),
        "since_id_honoured_anywhere": any(
            (s.get("since_id_probe") or {}).get("identical_to_page1_head") is False
            for s in stores
        ),
        "verdict_note": (
            "GO requires >=5 of 6 competitor stores at feed_ok DIRECTLY FROM THE "
            "PRODUCTION SERVER. A result produced anywhere else is a control "
            "measurement only and must not be used as the verdict."
        ),
    }


def print_human_summary(payload: Dict[str, Any]) -> None:
    run = payload["run"]
    egress = payload.get("egress") or {}
    summary = payload["summary"]
    ipinfo = egress.get("ipinfo") or {}

    print("")
    print("=" * 72)
    print("CompetitorTrack — Phase 0 probe summary")
    print("=" * 72)
    print("when            : %s" % payload["generated_at"])
    print("transport       : %s" % run["transport"])
    if run.get("proxy"):
        print("proxy           : %s" % run["proxy"])
    print("UA mode         : %s (robots agent token: %s)"
          % (run["ua_mode"], run["robots_agent_token"]))
    print("egress IP       : %s" % egress.get("ip"))
    print("reverse DNS     : %s" % egress.get("reverse_dns"))
    print("ASN / org       : %s" % ipinfo.get("org"))
    print("geo             : %s / %s" % (ipinfo.get("city"), ipinfo.get("country")))
    print("-" * 72)
    for entry in payload.get("smtp") or []:
        print(
            "smtp %s:%-4s tcp=%-5s tls=%-9s conclusive=%s"
            % (
                entry["host"],
                entry["port"],
                entry["tcp_connect"],
                entry.get("tls"),
                entry.get("conclusive"),
            )
        )
        print("    %s" % entry.get("assessment"))
    print("-" * 72)
    for store in payload["stores"]:
        stats = store.get("field_stats") or {}
        pag = store.get("pagination") or {}
        print(
            "%-26s %-10s %-20s total=%-5s available=%-6s inv_qty=%s"
            % (
                store["domain"][:26],
                store.get("verdict"),
                pag.get("completeness") or "-",
                pag.get("total_products_seen"),
                stats.get("available_key_present_pct"),
                stats.get("inventory_quantity_present_pct"),
            )
        )
        for note in store.get("notes") or []:
            print("    ! %s" % note)
    print("-" * 72)
    print("feed_ok         : %d / %d" % (summary["n_feed_ok"], summary["n_stores_probed"]))
    print("blocked (403/430): %s" % (summary["domains_blocked"] or "none"))
    print("rate limited     : %s" % (summary["domains_rate_limited"] or "none"))
    print("robots excluded  : %s" % (summary["domains_robots_disallowed"] or "none"))
    print("=" * 72)
    print(summary["verdict_note"])
    print("")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


async def run(args: argparse.Namespace) -> Dict[str, Any]:
    entries = parse_store_list(args.stores)
    if not entries:
        raise SystemExit("No stores found in %s" % args.stores)

    if args.ua == "bot":
        user_agent = BOT_UA_TEMPLATE.format(origin=args.bot_ua_origin.rstrip("/"))
    else:
        user_agent = BROWSER_UA

    headers = {"Accept": "application/json", "User-Agent": user_agent}
    timeout = httpx.Timeout(
        connect=args.connect_timeout,
        read=args.read_timeout,
        write=args.write_timeout,
        pool=5.0,
    )
    # httpx 0.28: proxy is a CONSTRUCTOR argument and takes ONE url.
    # The old `proxies={...}` dict was removed and raises TypeError.
    client_kwargs: Dict[str, Any] = {
        "headers": headers,
        "timeout": timeout,
        "trust_env": False,
        "follow_redirects": False,
    }
    if args.proxy:
        client_kwargs["proxy"] = args.proxy
    if args.ca_bundle:
        # A path, never False. Disabling verification would turn this probe into
        # a liability on a tool that reads arbitrary third-party hosts.
        client_kwargs["verify"] = args.ca_bundle

    payload: Dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": utc_now_iso(),
        "run": {
            "ua_mode": args.ua,
            "user_agent": user_agent,
            "robots_agent_token": robots_agent_token(user_agent),
            "transport": "proxy" if args.proxy else "direct",
            "proxy": redact_proxy(args.proxy),
            "delay_seconds": args.delay,
            "max_pages_probed": args.max_pages,
            "quick": args.quick,
            "fixtures_dir": args.fixtures_dir,
            "fixtures_max_pages": args.fixtures_max_pages,
            "ca_bundle": args.ca_bundle,
            "tls_verification": "enabled (custom CA bundle)"
            if args.ca_bundle
            else "enabled (default roots)",
            "python": platform.python_version(),
            "httpx": httpx.__version__,
            "host_platform": platform.platform(),
            "hostname": socket.gethostname(),
        },
        "stores": [],
    }

    async with httpx.AsyncClient(**client_kwargs) as client:
        print("[1/3] egress identity ...", flush=True)
        payload["egress"] = await egress_identity(client)

        if args.skip_smtp:
            payload["smtp"] = []
            payload["run"]["smtp_skipped"] = True
        else:
            print("[2/3] SMTP reachability (smtp.gmail.com 587 / 465) ...", flush=True)
            loop = asyncio.get_event_loop()
            payload["smtp"] = [
                await loop.run_in_executor(None, smtp_probe, "smtp.gmail.com", 587),
                await loop.run_in_executor(None, smtp_probe, "smtp.gmail.com", 465),
            ]

        print("[3/3] probing %d stores ..." % len(entries), flush=True)
        for index, (domain, collection, tier) in enumerate(entries, start=1):
            print("  -> (%d/%d) %s%s" % (index, len(entries), domain,
                                         (" /" + collection) if collection else ""),
                  flush=True)
            try:
                store = await probe_store(
                    client=client,
                    domain=domain,
                    collection_handle=collection,
                    tier=tier,
                    user_agent=user_agent,
                    delay=args.delay,
                    quick=args.quick,
                    max_pages=args.max_pages,
                    fixtures_dir=args.fixtures_dir,
                    fixtures_max_pages=args.fixtures_max_pages,
                )
            except Exception as exc:  # never lose the whole run for one store
                store = {
                    "domain": domain,
                    "collection_handle": collection,
                    "tier": tier,
                    "verdict": "probe_crashed",
                    "exception": type(exc).__name__,
                    "exception_detail": str(exc)[:300],
                    "notes": ["Probe raised; other stores were still processed."],
                }
            payload["stores"].append(store)
            if index < len(entries):
                await polite_sleep(args.delay)

    payload["summary"] = build_summary(payload["stores"])
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CompetitorTrack Phase 0 probe — run this ON THE PRODUCTION SERVER.",
    )
    parser.add_argument("--stores", required=True, help="path to the store list file")
    parser.add_argument("--out", default="phase0_results.json", help="results JSON path")
    parser.add_argument(
        "--fixtures-dir",
        default=None,
        help="write raw responses here (e.g. tests/fixtures/phase0). "
             "Required by the Phase 0 Definition of Done.",
    )
    parser.add_argument(
        "--fixtures-max-pages",
        type=int,
        default=1,
        help="how many paginated pages to persist as fixtures (default 1). "
             "A 250-product page is 1-3 MB, so persisting all 4 pages for 7 "
             "stores would put tens of MB in git for no test value: engine "
             "diff tests are built from page-1 pairs and pagination is tested "
             "with respx mocks.",
    )
    parser.add_argument("--ua", choices=("browser", "bot"), default="browser")
    parser.add_argument(
        "--bot-ua-origin",
        default="https://competitortrack.example.com",
        help="PUBLIC_ORIGIN used inside the honest bot UA string",
    )
    parser.add_argument("--proxy", default=None, help="single proxy URL (httpx 0.28 style)")
    parser.add_argument("--delay", type=float, default=2.5, help="polite delay, seconds")
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=20.0)
    parser.add_argument("--write-timeout", type=float, default=10.0)
    parser.add_argument(
        "--ca-bundle",
        default=os.environ.get("SSL_CERT_FILE") or None,
        help="path to a CA bundle. ONLY needed where something intercepts TLS "
             "(corporate proxy, CI sandbox) and httpx's bundled roots do not "
             "include the interceptor's CA. On a normal server, leave unset. "
             "Certificate verification is never disabled by this tool.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="pre-screen only: robots + meta + limit=1, no pagination, no since_id",
    )
    parser.add_argument("--skip-smtp", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    payload = asyncio.run(run(args))

    # Strip internal keys before writing.
    for store in payload["stores"]:
        store.pop("_page1_price_fingerprint", None)

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False, default=str)

    print_human_summary(payload)
    print("results written to: %s" % os.path.abspath(args.out))
    if args.fixtures_dir:
        print("fixtures written to: %s" % os.path.abspath(args.fixtures_dir))
    print("")
    print("NEXT: paste the contents of %s back into the build thread." % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
