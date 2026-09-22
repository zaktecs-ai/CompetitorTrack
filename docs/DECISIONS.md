# Decisions log

Spec §A0 requires: *"When something is genuinely unspecified, choose the simplest
option that keeps the tests passing and record the choice here."*

One entry per decision. Newest phase last.

---

## Phase 0

### D0.1 — No founder-owned store; the 7th slot is a stand-in

**Context.** P0 task 2 asks for "6 real beauty/skincare Shopify stores of different
sizes **plus the founder's own store**." The founder owns no Shopify store — he is
building CompetitorTrack to sell to merchants who do.

**Decision.** The 7th slot is filled by a **stand-in** store (`versedskin.com`),
labelled as such in `tools/stores_phase0.txt`. It is used only to generate
own-store fixtures for the `pg_trgm` title-similarity matching in the AI insight
layer (§A9), which needs two catalogs to match *between*.

**Consequence.** The `is_own_store` feature is still built in full — it exists for
tenants, not for the founder. It will be exercised against stand-in fixtures rather
than a live own store. No spec change.

---

### D0.2 — Probe targets Python 3.9+ as well as 3.12

**Context.** §A3 pins the application to Python 3.12. The probe, however, has to run
on whatever Python the Oracle box ships (Ubuntu 22.04 → 3.10, 24.04 → 3.12) and be
verifiable in the build sandbox (3.9).

**Decision.** `tools/phase0_probe.py` avoids 3.10-only syntax (no `match`, no
runtime `X | Y` unions; `from __future__ import annotations`). It runs on 3.9
through 3.12+.

**Consequence.** The probe could be validated end-to-end before hand-off instead of
being shipped untested. **This applies to `tools/` only** — application code under
`apps/api` targets 3.12 as specified.

---

### D0.3 — `--ca-bundle` escape hatch, never `verify=False`

**Context.** The build sandbox performs TLS interception, so httpx's bundled CA
roots rejected every request (`CERTIFICATE_VERIFY_FAILED`) while `curl` succeeded
against the same hosts using the system trust store.

**Decision.** The probe accepts `--ca-bundle <path>` (defaulting to `SSL_CERT_FILE`
if set) and records which bundle was used in the results JSON. Certificate
verification is **never** disabled.

**Rejected alternative.** `verify=False`. A tool that fetches arbitrary third-party
hosts must not silently accept any certificate, and a convenience flag added for a
sandbox quirk would have shipped to the production server too.

---

### D0.4 — Fixture persistence limited to page 1 by default

**Context.** The P0 Definition of Done requires raw-response fixtures under
`tests/fixtures/phase0/<store>/`. A 250-product page is 1–3 MB; persisting 4 pages
for 7 stores would add tens of MB to git.

**Decision.** `--fixtures-max-pages` (default **1**). Page 1 plus `meta.json`,
`robots.txt` and `products_limit1.json` are persisted per store.

**Rationale.** Engine diff tests are built from *pairs of page-1 snapshots*;
pagination, cap and page-repeat behaviour is tested with `respx` mocks, which need
no multi-megabyte fixtures. Nothing in the test plan (§A13) requires a real page 2.

---

### D0.5 — Unreadable `robots.txt` means "no consent", not "no rules"

**Context.** The first draft of the probe treated any non-200 `robots.txt` as
"no rules stated". That is correct for a 4xx and **wrong** for a 5xx or a transport
failure.

**Decision.** Mirror RFC 9309 and `urllib.robotparser`:

| `robots.txt` outcome | Interpretation |
|---|---|
| 200 with rules | Evaluate the rules; a `Disallow` on the feed path excludes the store |
| 4xx | No restrictions stated — crawling permitted |
| 5xx or transport failure | **Disallow-all.** Consent is not established; the store is marked `admissible: false` and excluded from the GO numerator |

**Consequence.** The probe still measures the feed for such a store (diagnosis is
the point) but the measurement cannot count toward the verdict. The same rule must
be carried into the production engine's weekly robots re-check.

---

### D0.6 — Registrable-domain comparison is a heuristic, not the Public Suffix List

**Context.** §A6.3 requires classifying a 3xx as "same registrable domain" (follow)
versus "redirected away" (reject).

**Decision.** The probe compares the last two labels, with a small allow-list of
two-label public suffixes (`co.uk`, `com.au`, `com.pk`, …).

**Consequence.** Accepted for a probe. **The production classifier must not ship
this heuristic** — it needs a real PSL implementation, because a wrong verdict there
either follows a redirect off-site (a security issue) or rejects a legitimate
`www.` redirect (a usability issue). Tracked as a P1 requirement.

---

### D0.7 — SMTP reachability must report "inconclusive" explicitly

**Context.** In the sandbox, `socket.create_connection()` to `smtp.gmail.com:587`
*succeeded* (`tcp_connect: true`, `connect_ms: 0`) while no SMTP greeting ever
arrived — the egress firewall accepted the socket and dropped it. Reporting that as
a pass would have been a false positive in the probe itself.

**Decision.** A port counts as reachable only when a `220` greeting is received
**and** TLS is established. TCP-accepted-but-silent is reported as
`conclusive: false` with an explicit assessment string.

**Consequence.** Sandbox SMTP results are marked inconclusive by construction. The
587/465 question is answerable only from the production server.

---

### D0.8 — No proxy is owned, so the proxy path ships untested

**Context.** §A6.7's `on_block` restart-via-proxy path and §A6.5's geo-pricing diff
both need a real proxy. The founder has none.

**Decision.** P0 runs **direct only**. `SCRAPER_PROXY_MODE` defaults to `off`.

**Consequence.** The achievable P0 verdicts are **GO** or **NO-GO** — `GO-WITH-PROXY`
cannot be confirmed without buying a proxy. The geo-suspect safeguard (§A6.5) is
still implemented and unit-tested with `respx`, because it must exist *before* a
proxy is ever switched on, not after. The empirical geo-pricing question stays open
and is recorded as a residual risk.
