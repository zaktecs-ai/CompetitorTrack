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

---

### D0.9 — `classify()` takes an expectation; one contract per endpoint

**Context.** The first shipped probe applied one success contract — "200 + parseable
JSON containing a `products` key" — to every endpoint it read. `/robots.txt` is
`text/plain` and `/meta.json` is JSON without a `products` key, so both were
recorded as `outcome: "error", error_code: "endpoint_disabled"` on all 7 stores
despite returning healthy 200s. The production evidence files carry this defect.

**Impact.** Zero effect on any decision: the downstream code branches on `status`,
not `outcome`, so robots rules were evaluated and currencies captured correctly
throughout (`robots.evaluation` and `meta.currency` are populated and right in
every record). The damage was to the *readability and credibility* of the artifact —
a results file in which every store appears to fail two of three fetches invites
the whole dataset to be dismissed.

**Decision.** `classify(..., expect=...)` selects the contract per endpoint:

| `expect` | Success means |
|---|---|
| `feed` | 200 + parseable JSON + a `products` key |
| `json` | 200 + parseable JSON of any shape |
| `text` | 200 with a non-empty body |

**Consequence.** Carry the same discipline into the production engine: §A6.3's
matrix is the **feed** classifier and must not be reused for `/robots.txt` or
`/meta.json`. A shared "classify any response" helper is how this defect would
reappear in `apps/api`.

---

### D0.10 — Geo-pricing answered by cross-continent comparison, not by proxy

**Context.** §A6.5 required a direct-vs-proxy price diff to settle whether
`/products.json` is geo-localised. No proxy is owned (D0.8), so that test was
recorded as permanently deferred.

**Observation.** Two runs existed from different continents 16 minutes apart — the
control run from AS14618 (Amazon, Ashburn US) and the production run from AS31898
(Oracle, Frankfurt DE). All seven page-1 responses were **byte-identical** across
both, and every derived statistic (variant counts, `compare_at` rates, zero-price
counts) matched exactly.

**Decision.** Treat the geo-localisation question as **answered in the negative for
this store set**, on stronger evidence than the planned proxy diff would have given
(byte-identity implies same currency, ordering and `compare_at` values, not merely
similar prices). Two further consequences are adopted:

1. The committed `tests/fixtures/phase0/` files, captured on the control IP, are
   **verified to be bit-for-bit what production receives**. This removes the
   caveat recorded under D0.4.
2. **§A6.5's geo-suspect safeguard is still built and tested.** It is retained not
   because localisation was observed but because two datacenter IPs in US-East and
   EU-Central do not cover every market, a Shopify Markets store could still
   localise, and the rule costs literally nothing while `SCRAPER_PROXY_MODE=off`
   (transport never changes, so it cannot fire). It is the only thing standing
   between a future proxy purchase and a store-wide false PRICE_DROP storm.

**Rejected alternative.** Dropping the geo-suspect rule as "empirically
unnecessary". A safeguard whose trigger condition is *"the thing we just measured
has changed"* must exist before the change, not after.

---

### D0.11 — Honest bot User-Agent adopted as the default

**Context.** Both production passes returned 7/7 with zero blocks and zero 429s, so
neither UA is forced by access. §A6.2 left the choice to the founder on Phase 0
evidence.

**Decision.** `SCRAPER_USER_AGENT = CompetitorTrackBot/1.0 (+{PUBLIC_ORIGIN}/bot)`.

**Rationale.** Zero measured access cost; robots.txt allowed the feed under the
`competitortrackbot` token on all 7 stores; it is defensible if a merchant asks who
we are; and it is a prerequisite for Web Bot Auth (§A6.8) and the higher Shopify
limits that come with signing.

**Accepted trade-off, stated plainly.** An identified crawler can be blocked by name
in `robots.txt`, and we will honour it. The browser UA avoids that only by being
indistinguishable from a human, which is exactly why it is not defensible. Revisit
only if a material share of target stores begin disallowing the token.

**Outstanding.** The UA currently embeds the placeholder
`https://competitortrack.example.com`. It must be regenerated with the real
`PUBLIC_ORIGIN` once a domain exists, and the `/bot` page it advertises must be
live before production traffic — otherwise the UA points at nothing, which is
worse than an anonymous one.
