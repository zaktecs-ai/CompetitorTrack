# CompetitorTrack

Multi-tenant B2B SaaS that tracks competitor **prices, sales, stock and catalog
changes** on Shopify stores in the beauty/skincare niche, and emails each tenant a
digest of meaningful changes with optional AI commentary.

---

## Status

| Phase | State |
|---|---|
| **P0 — validation spike** | ✅ **Complete — verdict GO.** 7/7 stores reachable directly from the production IP; no proxy required. [`docs/PHASE0_FINDINGS.md`](docs/PHASE0_FINDINGS.md) |
| **P1 — skeleton, compose, Caddy, health, heartbeat** | ✅ **Code complete.** Green in CI; the server-side checks are in [`docs/DEPLOY.md`](docs/DEPLOY.md) §7 and need a working DNS record first (§2) |
| P2 — data model & seed | ⬜ Ready to start |
| P3 — scraper & trigger engine | Not started |
| P4 — notifications & AI | Not started |
| P5 — frontend | Not started |
| P6 — hardening & go-live | Not started |

> ⚠️ **One thing is blocking the server-side finish of P1:** `jobsearchpk.site` is
> registered and paid for, but its nameservers point at DigitalOcean, which no
> longer hosts the zone — so nothing under the domain resolves and Let's Encrypt
> cannot validate it. Two steps fix it: [`docs/DEPLOY.md`](docs/DEPLOY.md) §2.

---

## Quickstart (local, no domain needed)

```bash
git clone https://github.com/zaktecs-ai/CompetitorTrack.git && cd CompetitorTrack
cp .env.example deploy/.env          # placeholder values are fine locally
cd deploy && docker compose up -d --build
docker compose run --rm api alembic upgrade head
```

Then open <http://localhost>. The placeholder dashboard fetches `/api/health` from
the browser and should show `api: ok`, `db: ok`, `scheduler: ok`.

Running `docker compose` from `deploy/` without `-f` auto-merges
`docker-compose.override.yml`: plain HTTP, insecure cookies, a log-only mailer, and
PostgreSQL published on `127.0.0.1:5432`. The server always passes
`-f docker-compose.yml` explicitly, which is what keeps the override out of
production.

For the server: [`docs/DEPLOY.md`](docs/DEPLOY.md).

---

## Repository layout

```
apps/api/                 FastAPI + the scheduler — one image, two entrypoints
  app/config.py           the [api] env section, validated at boot
  app/main.py             /api/health and /api/health/ready
  app/scheduler.py        `python -m app.scheduler` — singleton lock + heartbeat
  app/locks.py            PostgreSQL advisory locks (the only coordination primitive)
  app/net/domains.py      registrable-domain classification via the real PSL (D0.6)
  app/scraper/            empty in P1 — carries the one-contract-per-endpoint rule (D0.9)
  migrations/             Alembic, async; 0000 creates only `heartbeats`
  tests/                  94 tests, 19 of them against a real PostgreSQL
apps/web/                 Next.js 16, App Router, standalone output
  app/page.tsx            placeholder dashboard (Server Component shell)
  app/health-panel.tsx    the client component that reads /api/health
  app/bot/page.tsx        the public page our crawler's User-Agent advertises
deploy/                   docker-compose.yml + local override, Caddyfile, script stubs
docs/                     DEPLOY, DECISIONS, PHASE0_FINDINGS and Phase 0 evidence
tools/                    Phase 0 probe; the .env.example ↔ config.py parity checker
.github/workflows/ci.yml  ruff · pytest (real PostgreSQL) · eslint · tsc · next build
                          · compose + Caddyfile validation
.env.example              every variable, grouped exactly as §A12 lists them
```

---

## What P1 ships

- **Health with teeth.** `/api/health/ready` is the deploy gate — database only, so
  a scheduler that is still taking its lock cannot trigger a rollback.
  `/api/health` is what the uptime monitor pings and returns **503** when the
  database fails or the scheduler heartbeat is older than five minutes. A dead
  scheduler means nothing is being scraped, which is total product failure while
  every page still loads; that has to page someone.
- **A scheduler that cannot be run twice.** A session-level PostgreSQL advisory
  lock on its own connection, keyed by `blake2b('ct:scheduler')` computed in
  Python (never `hashtext()`, which is undocumented and 32-bit). A second
  instance logs `lock held, waiting` and does nothing — which is exactly what
  happens for a few seconds during every deploy.
- **One migration.** `0000_heartbeats`. The A5 schema is P2's `0001`.
- **The real Public Suffix List** (D0.6), replacing the probe's two-label
  heuristic before any redirect-following code exists.
- **An honest crawler identity that resolves** (D0.11): the User-Agent is built
  from `PUBLIC_ORIGIN` at startup — a template placeholder is refused at boot —
  and the `/bot` page it points at ships now, not after the first request.
- **Config that refuses to boot when it is dangerous:** `COOKIE_SECURE=false`
  outside localhost, a `JWT_SECRET` under 256 bits, a malformed Fernet key, a
  `DATABASE_URL` that does not name psycopg, a proxy mode with no proxy URLs.
- **`.env.example` checked against the code.** `tools/check_env_example.py` fails
  CI when a variable exists on one side only, in either direction.

## What P1 deliberately does not ship

No tables beyond `heartbeats`, no scraping, no triggers, no auth, no email, no AI,
no dashboard. The four deploy scripts are loud stubs that print the manual
commands and exit 3 (D1.11) — a deploy script that has never run against the real
server would be trusted on the day it matters, and P6 both implements and
rehearses them.

---

## Tests

```bash
cd apps/api
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest                      # DB-backed tests skip without a database
DATABASE_URL='postgresql+psycopg://ct:...@localhost:5432/competitortrack' \
  CT_REQUIRE_DB=1 .venv/bin/pytest    # ...and CI sets CT_REQUIRE_DB so they cannot

cd ../web && npm ci && npm run build && npm run typecheck && npm run lint
python3 ../../tools/check_env_example.py
```

`CT_REQUIRE_DB=1` exists because a suite that silently drops its integration
tests reports green while testing nothing.

---

## What Phase 0 established

Measured on the production host (Oracle A1, AS31898, Frankfurt) across 7 stores,
2,350 products and 1,796 variants. Full detail in
[`docs/PHASE0_FINDINGS.md`](docs/PHASE0_FINDINGS.md).

- **Direct egress works. No proxy needed.** 7/7 stores returned 200 + valid JSON on
  both a browser UA and an honest bot UA. Zero blocks, zero 429s — including ~120
  requests inside 5 minutes from one datacenter IP. This retires the project's
  largest unmeasured risk.
- **`/products.json` is not geo-localised.** All 7 page-1 responses were
  **byte-identical** between a US-East IP and a Frankfurt IP. Answered without a
  proxy, on stronger evidence than the planned proxy diff would have given.
- **Gmail SMTP is reachable** on 587 (STARTTLS) and 465 (implicit), TLSv1.3.
- **`inventory_quantity` is not exposed** — 0 of 1,796 variants. It can never be a
  trigger input.
- **`available` is present on 100%** of variants, so stock tracking is viable.
- **Prices are decimal strings**, and **10 of 1,796 variants are priced `0`** — the
  divide-by-zero guard is load-bearing on real data, not theoretical.
- **`since_id` is ignored**; `page=N` is the only pagination the feed has.
- **2 of 6 competitor stores exceed the 1,000-product cap** (both Shopify Plus
  brands), so collection scoping sits on the critical path of onboarding — not in
  the edge cases.
- **robots.txt allows the feed on all 7**, under both agent tokens; no store
  declared a `Crawl-delay`.

P0's probe and run instructions stay in the repo as
[`tools/README_PHASE0.md`](tools/README_PHASE0.md) — re-run them if a store starts
failing, if the server moves, or before pointing production at a proxy.

---

## Ground rules this repo follows

- **No fabricated results.** A verdict field stays `PENDING` until real numbers
  exist, and a check nobody has run is reported as not run. Control-run data is
  labelled as such everywhere it appears.
- **Every open choice is written down.** [`docs/DECISIONS.md`](docs/DECISIONS.md)
  has one entry per decision, with its context, its rationale and — where it
  matters — the rejected alternative.
- **Politeness is not optional.** 2.5 s delay ± 30% jitter between every request,
  strictly sequential per domain, robots.txt honoured, no UA rotation, no CAPTCHA
  circumvention.
- **TLS verification is never disabled.** The probe offers `--ca-bundle` for
  TLS-intercepting environments; it has no `--insecure`.
- **Secrets never land in output.** Proxy credentials are redacted to
  `scheme://host:port` in every artifact; no `*_enc` column or password field ever
  appears in an API response.

## Licence

None yet — private repository.
