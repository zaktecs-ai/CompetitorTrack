# Phase 0 — how to run the probe on the production server

**Why this has to run on the server:** Shopify's bot defences key off **IP reputation**.
The same request that returns `200` from a laptop can return `403` from a cloud IP.
A result produced anywhere except the machine that will run production is a *control
measurement*, never the verdict. So please run this on the Oracle A1 instance.

Nothing here writes to a database, sends mail, or logs in anywhere. It reads public
endpoints and records what it saw.

---

## Step 1 — get the code onto the server (2 min)

SSH in, then:

```bash
sudo apt-get update -y && sudo apt-get install -y git python3-venv
git clone https://github.com/zaktecs-ai/CompetitorTrack.git
cd CompetitorTrack
```

If you already cloned it earlier, just `git pull`.

---

## Step 2 — one-time Python setup (2 min)

`httpx` is not preinstalled on a bare Ubuntu box, so give it its own virtualenv:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install 'httpx[socks]'
```

Check it took:

```bash
python3 -c "import httpx, sys; print('httpx', httpx.__version__, '| python', sys.version.split()[0])"
```

> The probe runs on Python 3.9+ as well as 3.12, so whatever Ubuntu gives you is fine.

---

## Step 3 — pass 1: browser User-Agent, direct (≈4 min)

```bash
python3 tools/phase0_probe.py \
  --stores tools/stores_phase0.txt \
  --ua browser \
  --fixtures-dir tests/fixtures/phase0 \
  --out phase0_results.browser.json
```

It prints a live summary and writes the JSON. **Read the summary** — if every store
says `blocked`, stop and report that; there is no point running pass 2.

---

## Step 4 — wait 30 minutes, then pass 2: honest bot User-Agent (≈4 min)

**The gap matters.** If you run both passes back to back, the second one inherits
any rate-limit state the first one caused, and the answer to "which UA fares
better?" comes out wrong. Half an hour is enough.

```bash
python3 tools/phase0_probe.py \
  --stores tools/stores_phase0.txt \
  --ua bot \
  --bot-ua-origin https://YOUR-DOMAIN-HERE \
  --out phase0_results.bot.json
```

Don't have a domain yet? Leave the flag off — it falls back to a placeholder, and
the UA string is still a valid honest-bot identifier for comparison purposes.

---

## Step 5 — send the results back

```bash
cat phase0_results.browser.json
```

Paste that into the build thread, then the same for `phase0_results.bot.json`.
If the output is too big to paste, this works too:

```bash
# writes one small file with just the decision-relevant parts
python3 - <<'PY' > phase0_summary.txt
import glob, json
for path in sorted(glob.glob("phase0_results.*.json")):
    d = json.load(open(path))
    print("###", path)
    print(json.dumps({"run": d["run"], "egress": d["egress"],
                      "smtp": d["smtp"], "summary": d["summary"]}, indent=2))
    for s in d["stores"]:
        print("--", s["domain"], s.get("verdict"),
              (s.get("pagination") or {}).get("completeness"))
        for n in s.get("notes") or []:
            print("     !", n)
PY
cat phase0_summary.txt
```

---

## Optional — proxy pass (only if you buy a proxy)

You have no proxy today, so **skip this**. It's documented for later: if pass 1
comes back mostly `blocked`, a proxy is the escape hatch, and this pass is what
measures whether it actually helps *and* whether it shifts prices (geo-pricing).

```bash
python3 tools/phase0_probe.py \
  --stores tools/stores_phase0.txt \
  --ua browser \
  --proxy 'socks5h://user:pass@proxy-host:1080' \
  --out phase0_results.proxy.json
```

Only **residential or ISP** proxies help — datacenter proxies are cloud IPs and
trip the same filters. Pin the proxy's country to the store's home market, or the
prices you read may not be the prices the merchant's own customers see. Your
credentials never appear in the output file (redacted to `scheme://host:port`).

---

## Troubleshooting

| Symptom | What it means | Do this |
|---|---|---|
| `ERROR: httpx is not installed` | venv not activated | `. .venv/bin/activate` |
| Every store `error_code=network` with `CERTIFICATE_VERIFY_FAILED` | something is intercepting TLS | `--ca-bundle /etc/ssl/certs/ca-certificates.crt`. Verification is never disabled. |
| Every store `error_code=blocked` (403/430) | the server's IP is blocked | This is a real finding — report it. It means `GO-WITH-PROXY` or `NO-GO`. |
| One store `error_code=rate_limited` (429) | you hit it too fast | Raise `--delay 5` and re-run just that store |
| `robots.txt UNREADABLE` | 5xx or network failure | Store can't enter the set until robots is readable — not a probe bug |
| SMTP rows say `INCONCLUSIVE` | TCP accepted, no `220` greeting | Means a firewall ate it. On the Oracle box it should say `reachable`. |
| Takes longer than ~6 min | normal | 2.5 s polite delay between every request, by design |

---

## What the numbers mean

| Field | Why it matters |
|---|---|
| `egress.ip` / `ipinfo.org` | Proves the run came from the production IP, not a laptop |
| `summary.n_admissible_feed_ok_and_robots_consent` | The GO/NO-GO numerator: needs **≥5 of 6** |
| `pagination.completeness` | `partial_cap_exceeded` ⇒ that store needs collection scoping before it can ever alert |
| `field_stats.available_key_present_pct` | Drives `stores.stock_tracking_enabled`. Below 95% ⇒ stock tracking off for that store |
| `field_stats.inventory_quantity_present_pct` | Settles the spec's open question on whether the feed exposes it |
| `since_id_probe.interpretation` | Confirms there is no cursor, so `page=N` is the only pagination |
| `smtp[].assessment` | Whether the server can reach Gmail on 587/465 (port 25 is permanently blocked on Oracle — irrelevant, we don't use it) |
| `meta.currency` | Feeds `stores.currency_minor_unit`; a 0-decimal currency (JPY/KRW) must parse differently |

---

## Verdict rule (from the spec, not negotiable)

| Verdict | Condition |
|---|---|
| **GO** | ≥5 of the 6 competitor stores return 200 + valid JSON **directly** |
| **GO-WITH-PROXY** | That only holds through a proxy — states which `SCRAPER_PROXY_MODE` to use |
| **NO-GO** | Neither — report and stop. Do not build phases 1–6. |

A `NO-GO` is not a failure of the project. It is the cheapest possible discovery
that the approach needs changing, found in one day instead of six weeks.
