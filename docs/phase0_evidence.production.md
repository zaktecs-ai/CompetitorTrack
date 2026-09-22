# Phase 0 — production run evidence

Verbatim output from the two probe passes executed on the production server by the
founder on 2026-09-22. Transcribed into the repository because the runner has no
push credentials; the full raw JSONs remain on the box at
`~/CompetitorTrack/phase0_results.browser.json` and `…bot.json`.

Host: `zakria-data-instance`, `Linux-6.17.0-1018-oracle-aarch64-with-glibc2.39`,
Python 3.12.3, httpx 0.28.1.

---

## Pass 1 — browser User-Agent, direct

```
$ python3 tools/phase0_probe.py \
    --stores tools/stores_phase0.txt --ua browser \
    --fixtures-dir tests/fixtures/phase0 \
    --out phase0_results.browser.json

========================================================================
CompetitorTrack — Phase 0 probe summary
========================================================================
when            : 2026-09-22T07:10:08+00:00
transport       : direct
UA mode         : browser (robots agent token: mozilla)
egress IP       : 130.61.153.125
reverse DNS     : None
ASN / org       : AS31898 Oracle Corporation
geo             : Frankfurt am Main / DE
------------------------------------------------------------------------
smtp smtp.gmail.com:587  tcp=True  tls=starttls  conclusive=True
    reachable — TLS established after a valid 220 greeting
smtp smtp.gmail.com:465  tcp=True  tls=implicit  conclusive=True
    reachable — TLS established after a valid 220 greeting
------------------------------------------------------------------------
colourpop.com              feed_ok    partial_cap_exceeded total=1000  available=100.0  inv_qty=0.0
fentybeauty.com            feed_ok    partial_cap_exceeded total=1000  available=100.0  inv_qty=0.0
theinkeylist.com           feed_ok    complete             total=137   available=100.0  inv_qty=0.0
kravebeauty.com            feed_ok    complete             total=40    available=100.0  inv_qty=0.0
herbivorebotanicals.com    feed_ok    complete             total=51    available=100.0  inv_qty=0.0
saltandstone.com           feed_ok    complete             total=46    available=100.0  inv_qty=0.0
versedskin.com             feed_ok    complete             total=76    available=100.0  inv_qty=0.0
------------------------------------------------------------------------
feed_ok         : 7 / 7
blocked (403/430): none
rate limited     : none
robots excluded  : none
========================================================================
```

## Pass 2 — honest bot User-Agent, direct

Run at 07:14:55 UTC, **~5 minutes** after pass 1 rather than the 30 minutes the
README asks for. See `PHASE0_FINDINGS.md` §1 — the deviation strengthens the
result rather than invalidating it, because ~120 requests in 5 minutes from one
datacenter IP still produced zero throttling.

```
$ python3 tools/phase0_probe.py \
    --stores tools/stores_phase0.txt --ua bot \
    --out phase0_results.bot.json

when            : 2026-09-22T07:14:55+00:00
transport       : direct
UA mode         : bot (robots agent token: competitortrackbot)
egress IP       : 130.61.153.125
ASN / org       : AS31898 Oracle Corporation
geo             : Frankfurt am Main / DE
------------------------------------------------------------------------
smtp smtp.gmail.com:587  tcp=True  tls=starttls  conclusive=True
smtp smtp.gmail.com:465  tcp=True  tls=implicit  conclusive=True
------------------------------------------------------------------------
(all 7 stores identical to pass 1)
feed_ok         : 7 / 7
blocked (403/430): none
rate limited     : none
robots excluded  : none
```

---

## `run` block (pass 2)

```json
{
  "ua_mode": "bot",
  "user_agent": "CompetitorTrackBot/1.0 (+https://competitortrack.example.com/bot)",
  "robots_agent_token": "competitortrackbot",
  "transport": "direct",
  "proxy": null,
  "delay_seconds": 2.5,
  "max_pages_probed": 4,
  "quick": false,
  "fixtures_dir": null,
  "fixtures_max_pages": 1,
  "ca_bundle": null,
  "tls_verification": "enabled (default roots)",
  "python": "3.12.3",
  "httpx": "0.28.1",
  "host_platform": "Linux-6.17.0-1018-oracle-aarch64-with-glibc2.39",
  "hostname": "zakria-data-instance"
}
```

> `--bot-ua-origin` was left at its placeholder because no domain is registered
> yet. The UA string must be regenerated with the real `PUBLIC_ORIGIN` before
> production traffic, and the `/bot` page it points at must exist (§A6.2).

## `egress` block

```json
{
  "ip": "130.61.153.125",
  "reverse_dns": null,
  "ipinfo": {
    "ip": "130.61.153.125",
    "hostname": null,
    "city": "Frankfurt am Main",
    "region": "Hesse",
    "country": "DE",
    "org": "AS31898 Oracle Corporation",
    "timezone": "Europe/Berlin"
  }
}
```

## `smtp` block — both ports conclusively reachable

```json
[
  {
    "host": "smtp.gmail.com", "port": 587,
    "tcp_connect": true,
    "banner": "220 smtp.gmail.com ESMTP ffacd0b85a97d-4886277406bsm2931383f8f.12 - gsmtp",
    "tls": "starttls", "tls_version": "TLSv1.3",
    "starttls_advertised": true,
    "starttls_reply": "220 2.0.0 Ready to start TLS",
    "conclusive": true,
    "assessment": "reachable — TLS established after a valid 220 greeting"
  },
  {
    "host": "smtp.gmail.com", "port": 465,
    "tcp_connect": true,
    "banner": "220 smtp.gmail.com ESMTP 5b1f17b1804b1-49fdad53b53sm26600245e9.14 - gsmtp",
    "tls": "implicit", "tls_version": "TLSv1.3",
    "conclusive": true,
    "assessment": "reachable — TLS established after a valid 220 greeting"
  }
]
```

Confirms §A8.7: Oracle Cloud permanently blocks outbound port 25, but 587 and 465
are open. Per-tenant SMTP and the platform mailer will both work from this host.

## `summary` block (pass 2)

```json
{
  "n_stores_probed": 7,
  "n_feed_ok": 7,
  "n_blocked_403_430": 0,
  "n_rate_limited_429": 0,
  "n_robots_disallowed": 0,
  "available_key_pct_min": 100.0,
  "available_key_pct_max": 100.0,
  "inventory_quantity_pct_min": 0.0,
  "inventory_quantity_pct_max": 0.0,
  "page_repeat_domains": [],
  "n_admissible_feed_ok_and_robots_consent": 7,
  "domains_robots_unreadable": [],
  "domains_exceeds_cap": ["colourpop.com", "fentybeauty.com"],
  "domains_complete_catalog": [
    "theinkeylist.com", "kravebeauty.com", "herbivorebotanicals.com",
    "saltandstone.com", "versedskin.com"
  ],
  "inventory_quantity_exposed_anywhere": false,
  "since_id_honoured_anywhere": false
}
```

---

## Per-store figures used in the findings

Variant statistics are page 1. `zero` = variants priced `0`; `cmpAt` = live
`compare_at_price` rate.

| Store | Currency | Country | Shop name | Products | Variants | cmpAt | zero | p1 ms | Completeness |
|---|---|---|---|---|---|---|---|---|---|
| colourpop.com | USD | US | ColourPop | 1,000 (4 full pages) | 250 | 0.8% | 0 | 384 | `partial_cap_exceeded` |
| fentybeauty.com | USD | US | Fenty Beauty | 1,000 (4 full pages) | 254 | 6.69% | 4 | 121 | `partial_cap_exceeded` |
| theinkeylist.com | GBP | GB | INKEY UK | 137 | 146 | 53.42% | 4 | 355 | `complete` |
| kravebeauty.com | USD | US | KraveBeauty | 40 | 60 | 48.33% | 0 | 144 | `complete` |
| herbivorebotanicals.com | USD | US | Herbivore Botanicals | 51 | 62 | 14.52% | 1 | 251 | `complete` |
| saltandstone.com | USD | US | SALT & STONE | 46 | 147 | 36.73% | 1 | 218 | `complete` |
| versedskin.com | USD | US | Versed Skin | 76 | 877 | 68.99% | 0 | 341 | `complete` |

Fenty Beauty's later pages carried 265 / 310 / 321 variants with `compare_at`
rates of 2.26% / 35.48% / 16.82% and 5 further zero-priced variants on page 2 —
the feed is ordered newest-first, so one page is not representative of a catalog.

### Same-domain 301s observed (§A6.3 redirect path, exercised for real)

| Store | Request | Status | Location | Hops followed |
|---|---|---|---|---|
| theinkeylist.com | `/robots.txt` | 301 | `https://uk.theinkeylist.com/robots.txt` | 1 |
| herbivorebotanicals.com | `/robots.txt` | 301 | `https://www.herbivorebotanicals.com/robots.txt` | 1 |
| saltandstone.com | `/robots.txt` | 301 | `https://www.saltandstone.com/robots.txt` | 1 |

No `/products.json` request redirected on any store, and the `www.` variant of
every domain served the feed directly with 200 and 0 hops.

### robots.txt verdicts

All 7 stores: HTTP 200, `policy: rules_read`, `/products.json` **allowed**,
`crawl_delay: null`, `mentions_products_json: false`. Evaluated as agent token
`mozilla` in pass 1 and `competitortrackbot` in pass 2 — allowed under both.

---

## Known artifact defect in these two runs

Both passes were produced by the probe **before** the `classify()` expectation fix.
In these JSONs, the `robots.fetch` and `meta.fetch` records read:

```json
{ "status": 200, "outcome": "error", "error_code": "endpoint_disabled" }
```

That is wrong, and it is a defect in the probe, not in the stores. `classify()`
applied the product-feed success contract ("200 + JSON + a `products` key") to
`/robots.txt` (`text/plain`) and `/meta.json` (JSON with no `products` key), so
both were labelled as failures despite being successful 200 responses.

**No decision in this document was affected.** The downstream code keys off
`status`, not `outcome`, so robots rules were parsed and currencies captured
correctly on every store — visible in the `robots.evaluation` and `meta.currency`
fields above, which are populated and correct. The defect was purely in how the
record *reads*.

Fixed in `classify(..., expect="feed"|"json"|"text")`; see `DECISIONS.md` D0.9.
Any re-run will report `outcome: "ok"` on these two endpoints.
