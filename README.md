# CompetitorTrack

Multi-tenant B2B SaaS that tracks competitor **prices, sales, stock and catalog
changes** on Shopify stores in the beauty/skincare niche, and emails each tenant a
digest of meaningful changes with optional AI commentary.

---

## Status

| Phase | State |
|---|---|
| **P0 — validation spike** | 🟡 In progress — probe built and self-validated; **awaiting the run from the production IP** |
| P1 — skeleton & deploy | Not started |
| P2 — data model & seed | Not started |
| P3 — scraper & trigger engine | Not started |
| P4 — notifications & AI | Not started |
| P5 — frontend | Not started |
| P6 — hardening & go-live | Not started |

> **P0 is a gate.** Shopify's bot defences key off IP reputation, so the question
> "is the public product feed usable from the machine that will run production?"
> has to be answered *before* any application code is written. A `NO-GO` here means
> the approach changes — and finding that out in a day beats finding it out in six
> weeks.

**👉 To move P0 forward, follow [`tools/README_PHASE0.md`](tools/README_PHASE0.md).**

---

## What is in the repo right now

```
tools/
  phase0_probe.py          Phase 0 validation probe (no app code, no DB, read-only)
  README_PHASE0.md         Copy-paste run instructions for the production server
  stores_phase0.txt        The 7-store Phase 0 set (6 competitors + 1 stand-in)
  stores_candidates.txt    The 12 candidates the set was screened from
docs/
  PHASE0_FINDINGS.md       Findings so far; verdict field reads PENDING
  DECISIONS.md             Every choice the spec left open, with its rationale
  phase0_results.control-dev-ip.json
                           Control run — from a build-sandbox AWS IP, NOT the verdict
tests/fixtures/phase0/     Raw responses per store (page 1, meta, robots, limit=1)
```

Nothing here imports a web framework or touches a database. That starts in P1.

---

## Findings already settled

These come from the feed's format and the merchants' own configuration, so they do
not depend on which IP we ask from — they are usable now. Full detail and sample
sizes in [`docs/PHASE0_FINDINGS.md`](docs/PHASE0_FINDINGS.md).

- **`inventory_quantity` is not exposed** on `/products.json` — 0 of 1,796 variants.
  It can never be a trigger input.
- **`available` is present on 100%** of variants, so stock tracking is viable.
- **Prices are decimal strings**, and **10 of 1,796 variants are priced `0`** — the
  divide-by-zero guard is load-bearing on real data, not theoretical.
- **`since_id` is ignored**; `page=N` is the only pagination the storefront feed has.
- **2 of 6 competitor stores exceed the 1,000-product cap** (both Shopify Plus
  brands), so collection scoping is on the critical path of onboarding — not an
  edge case.
- **robots.txt allows the feed on all 7 stores**; no store declared a `Crawl-delay`.

Still open, and answerable only from the server: whether those stores return `200`
from the Oracle A1 IP, which User-Agent fares better, and whether the box can reach
Gmail on 587/465.

---

## Ground rules this repo follows

- **No fabricated results.** The verdict field stays `PENDING` until real production
  numbers exist. Control-run data is labelled as such everywhere it appears.
- **Politeness is not optional.** 2.5 s delay ± 30% jitter between every request,
  strictly sequential per domain, robots.txt honoured, no UA rotation, no CAPTCHA
  circumvention.
- **TLS verification is never disabled.** The probe offers `--ca-bundle` for
  TLS-intercepting environments; it has no `--insecure`.
- **Secrets never land in output.** Proxy credentials are redacted to
  `scheme://host:port` in every artifact.

## Licence

None yet — private repository.
