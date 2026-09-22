# CompetitorTrack

Multi-tenant B2B SaaS that tracks competitor **prices, sales, stock and catalog
changes** on Shopify stores in the beauty/skincare niche, and emails each tenant a
digest of meaningful changes with optional AI commentary.

---

## Status

| Phase | State |
|---|---|
| **P0 — validation spike** | ✅ **Complete — verdict GO.** 7/7 stores reachable directly from the production IP; no proxy required. See [`docs/PHASE0_FINDINGS.md`](docs/PHASE0_FINDINGS.md). |
| P1 — skeleton & deploy | ⬜ Ready to start |
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

The gate is passed. P0's probe and run instructions stay in the repo as
[`tools/README_PHASE0.md`](tools/README_PHASE0.md) — re-run them if a store starts
failing, if the server moves, or before pointing production at a proxy.

---

## What is in the repo right now

```
tools/
  phase0_probe.py          Phase 0 validation probe (no app code, no DB, read-only)
  README_PHASE0.md         Copy-paste run instructions for the production server
  stores_phase0.txt        The 7-store Phase 0 set (6 competitors + 1 stand-in)
  stores_candidates.txt    The 12 candidates the set was screened from
docs/
  PHASE0_FINDINGS.md       Verdict GO, with the full production evidence
  phase0_evidence.production.md
                           Verbatim console + JSON blocks from the server runs
  DECISIONS.md             Every choice the spec left open, with its rationale
  phase0_results.control-dev-ip.json
                           Control run — from a build-sandbox AWS IP, NOT the verdict
tests/fixtures/phase0/     Raw responses per store (page 1, meta, robots, limit=1)
```

Nothing here imports a web framework or touches a database. That starts in P1.

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

Two probe defects were found and fixed during the phase, and one artifact defect is
documented rather than hidden — see `DECISIONS.md` D0.9.

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
