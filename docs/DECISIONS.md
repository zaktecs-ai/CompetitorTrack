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

## Phase 1

### D1.1 — P0 reached `main` through a pull request, not a push

**Context.** The P1 brief said to read `README.md`, `docs/PHASE0_FINDINGS.md` and
`docs/DECISIONS.md` "from main". They were not there: `main` held a single commit
(`899a552 chore: initialise repository`) with a stale README claiming P0 was still
awaiting the production run. All four P0 commits lived on
`phase0/validation-spike`.

**Decision.** Merge `phase0/validation-spike` into `main` through a PR before
starting P1, then branch `p1/skeleton` off `main`.

**Rationale.** `main` is what every later phase prompt will read, what CI runs on
and what `deploy.sh <sha>` checks out. A phase that begins by reading the wrong
tree begins by making the wrong decisions. A merge commit (not squash) keeps the
four P0 commits and their original SHAs intact, which matters because
`PHASE0_FINDINGS.md` cites them as provenance.

**Consequence.** Every phase from here ends with its branch merged to `main`, so
"read it from main" stays true.

---

### D1.2 — `publicsuffixlist` with private-section rules (discharges D0.6)

**Context.** D0.6 recorded that the probe's registrable-domain heuristic — last
two labels plus a small allow-list — **must not ship**, and tracked a real Public
Suffix List implementation as a P1 requirement.

**Decision.** `publicsuffixlist==1.0.2.20260921`, wrapped in
`apps/api/app/net/domains.py`. The dataset ships inside the wheel, so there is no
network access at import and no refresh job; the pinned version *is* the dataset
version, refreshed deliberately like any other dependency.
`privatesuffix()` is used rather than the ICANN-only view.

**Rationale for the private section.** It puts the boundary below
`myshopify.com`, so `one.myshopify.com` and `two.myshopify.com` are correctly
*different* sites. For a redirect-follow decision the tighter boundary is the
safe one: the cost of being too tight is a rejected store, the cost of being too
loose is following a 3xx off-site.

**Consequence.** §A6.3's redirect classifier (P3) calls
`same_registrable_domain()` and must never re-implement the comparison. The three
same-domain redirects Phase 0 actually recorded — `www.herbivorebotanicals.com`,
`www.saltandstone.com`, `uk.theinkeylist.com` — are unit tests, alongside the
foreign-redirect cases (`store.com` → `store.com.evil.net`) that the heuristic
would have got wrong.

---

### D1.3 — D0.9 is discharged by module layout, not by a comment

**Context.** D0.9: the probe applied one success contract to every endpoint, so
healthy 200s from `/robots.txt` and `/meta.json` were recorded as
`endpoint_disabled` on all seven stores. The decision ends "a shared 'classify
any response' helper is how this defect would reappear in `apps/api`".

**Decision.** `apps/api/app/scraper/__init__.py` exists in P1 containing only a
docstring that names the three separate classifiers P3 must write
(`classify_feed.py`, `classify_meta.py`, `classify_robots.py`), states what
"success" means for each, and says plainly that a generic classifier
re-introduces the Phase 0 defect. No scraping code is written in P1.

**Rationale.** A constraint recorded only in `DECISIONS.md` is a constraint
nobody reads while writing `scraper/`. Put where the code will be written, it is
read by whoever is about to break it.

---

### D1.4 — `env_file` for the api and scheduler, explicit `environment` elsewhere

**Context.** The `[api]` section has 21 variables and both the `api` and
`scheduler` service need all of them.

**Decision.** Those two services take `env_file: .env`; `db`, `caddy` and `web`
take explicit `environment:` mappings.

**Rationale.** 42 lines of YAML repeating what `.env.example` already documents
would drift, and the drift would be silent. It is not silent for the `[api]`
section specifically, because `tools/check_env_example.py` fails CI when the
file and `Settings` disagree. `Settings` is `extra="ignore"`, so the handful of
non-api variables in the file are harmless to the process.

**Consequence.** The api container's environment also contains `POSTGRES_*` and
the backup paths. Nothing reads them, and `POSTGRES_PASSWORD` is already inside
`DATABASE_URL`, so no new secret is exposed.

---

### D1.5 — "empty `ACME_CA` means production" is expressed as a Caddyfile default

**Context.** §A12 says an empty `ACME_CA` means production Let's Encrypt and
the staging URL is used during setup. But `acme_ca` with an empty argument is a
Caddyfile **syntax error** — Caddy would refuse to start, which on a fresh server
looks exactly like a certificate problem.

**Decision.** The Caddyfile reads
`acme_ca {$ACME_CA:https://acme-v02.api.letsencrypt.org/directory}`.

**Consequence.** The specified semantics hold — clearing the variable yields
production certificates — without a configuration that cannot parse.
`.env.example` ships the staging URL, and clearing it is an explicit go-live step
in P6.

---

### D1.6 — The scheduler's orphan-run reaper arrives with the table it reaps

**Context.** §A6.11 has the scheduler mark leftover `scrape_runs` rows with
`status='running'` as `aborted` immediately after taking the singleton lock.
`scrape_runs` is created by P2's `0001`.

**Decision.** P1's scheduler takes the lock and beats; the abort step is written
in P2, in the same change that creates the table. The requirement is recorded in
the module docstring so it cannot be forgotten.

**Rationale.** The alternative — a guarded query against a table that may not
exist — is code whose only purpose is to tolerate a state that lasts one phase.

---

### D1.7 — `migrations/env.py` reads `DATABASE_URL` directly, not through `Settings`

**Context.** `Settings` requires `JWT_SECRET` and `MASTER_ENCRYPTION_KEYS`.
`deploy.sh` runs `alembic upgrade head` in a one-shot container.

**Decision.** `env.py` reads `os.environ["DATABASE_URL"]` and raises a message
naming the compose command if it is missing.

**Rationale.** A migration is not the application. Failing a schema upgrade
because an unrelated secret is absent would be a self-inflicted outage during the
exact five minutes of a deploy when nothing else should be able to go wrong.

---

### D1.8 — The whole dependency set is pinned in P1, and the image refuses source builds

**Context.** §A3 claims every dependency has a manylinux aarch64 wheel and that
"nothing compiles from source on the A1". Images are built on the server, so a
missing wheel is discovered during a deploy.

**Decision.** `apps/api/requirements.txt` pins the **complete** MVP runtime set
now — including `httpx`, `pwdlib`, `PyJWT`, `slowapi`, `cryptography`,
`aiosmtplib` and `google-genai`, which P1 does not import — each tagged with the
phase that first uses it. The Dockerfile installs with `--only-binary=:all:`, and
CI installs the same way.

**Rationale.** It converts §A3's claim into a build-time assertion, and it
converts it *now*: the first `docker compose build` on the A1 proves the whole
MVP's wheel availability instead of P4 discovering that `google-genai` drags in
something that needs a compiler. Verified locally: all runtime and dev pins
resolve to wheels on cp312.

---

### D1.9 — The User-Agent is built from `PUBLIC_ORIGIN` at startup, and `/bot` ships now

**Context.** D0.11 adopted the honest bot UA and left an open item: the string
embedded the placeholder `https://competitortrack.example.com`, and the `/bot`
page it advertises did not exist.

**Decision.** `SCRAPER_USER_AGENT` holds a template containing at most the token
`{PUBLIC_ORIGIN}`, which `Settings.user_agent` interpolates at startup;
`PUBLIC_ORIGIN` itself is validated as scheme-plus-host. Any other `{…}`
placeholder is rejected at boot. The static `/bot` page — what we fetch, how
politely, and the exact `robots.txt` lines that stop us — ships in P1.

**Rationale.** A named crawler pointing at a 404 is worse than an anonymous one.
Both halves had to exist before P3 makes the first request, and both are cheap
now.

---

### D1.10 — ESLint stays on 9.x

**Context.** ESLint 10 is current and npm marks 9.x as unsupported.
`eslint-config-next@16.3.5` declares `eslint >=9`, so 10 installs.

**Decision.** Pin `eslint@^9.39.5`.

**Evidence.** With ESLint 10 the lint run dies before reporting anything:
`TypeError: Error while loading rule 'react/display-name':
contextOrFilename.getFilename is not a function` — `eslint-plugin-react`, vendored
inside `eslint-config-next`, uses an API ESLint 10 removed.

**Consequence.** `npm install` prints a deprecation warning for eslint 9. A
warning is preferable to a linter that cannot run. Revisit when
`eslint-config-next` ships an ESLint 10-compatible plugin set.

---

### D1.11 — The four deploy scripts ship as loud stubs

**Context.** P1's task list asks for `deploy/scripts/{deploy,rollback,backup,restore}.sh`
"as documented stubs that fail loudly if unimplemented".

**Decision.** Each script sets `set -euo pipefail`, prints the manual commands
that do the same job, and exits 3. Each carries the full intended implementation
as a numbered comment block taken from §A12. CI has **no** deploy job in P1.

**Rationale.** A deploy script that has never run against the real server would
be trusted on the day it matters. The manual sequence in `docs/DEPLOY.md` is short
and reviewable; P6 implements the scripts and rehearses the backup/restore pair
against a throwaway volume, which is the only way a backup stops being a rumour.

---

### D1.12 — Database-backed tests skip locally, never in CI

**Context.** §A13 requires a real PostgreSQL. A developer without one would
otherwise see a wall of errors.

**Decision.** The `migrated_database` fixture connects (a real connection, not a
TCP probe, so unix sockets work) and `pytest.skip`s when there is nothing there
— unless `CT_REQUIRE_DB=1`, which CI sets, in which case it fails.

**Rationale.** Skipping is a convenience for a laptop and a catastrophe in CI: a
suite that silently drops its integration tests reports green while testing
nothing.

---

### D1.13 — A missing heartbeat is unhealthy, not unknown-and-fine

**Context.** §A12 specifies 503 from `/api/health` when the database fails or the
heartbeat is older than five minutes. It does not say what a *missing* heartbeat
row means — a database whose scheduler has never run.

**Decision.** `scheduler: "unknown"` and HTTP **503**.

**Rationale.** The endpoint answers "is the system doing its job?" and a
scheduler that has never beaten is not. It self-resolves within a minute of a
healthy start, because the heartbeat job's first run is immediate rather than one
interval away. `/api/health/ready` stays 200 throughout, so the deploy gate is
unaffected.

---

### D1.14 — `COOKIE_SECURE=false` is refused off localhost

**Context.** The flag exists for the local HTTP override.

**Decision.** `Settings` raises at startup if `COOKIE_SECURE` is false while
`PUBLIC_ORIGIN` is not `http://localhost` or `http://127.0.0.1`.

**Rationale.** The failure mode of the alternative is session cookies travelling
in clear on a public domain, caused by one leftover line in `.env`. Refusing to
boot is a better outcome than serving.

---

### D1.15 — `app.jobsearchpk.site`, and its DNS is currently broken

**Context.** P1 needs a hostname for `SERVER_NAME`, `PUBLIC_ORIGIN` and the
crawler's `/bot` URL. The founder owns `jobsearchpk.site`, bought from Hostinger.

**Decision.** `app.jobsearchpk.site`. A subdomain keeps the apex free for a
marketing site later, and certificate issuance is per-hostname either way.

**Finding, recorded because it blocks the server-side Definition of Done.**
The domain is registered and paid until 2027-05-20 (registrar: Hostinger), but
its nameservers are delegated to `ns1/ns2/ns3.digitalocean.com`, and those
servers answer `REFUSED` — the zone does not exist in any DigitalOcean account.
So nothing under `jobsearchpk.site` resolves at all today: no A record, no SOA,
no NS. HTTP-01 certificate issuance cannot work until that is fixed.
`docs/DEPLOY.md` §2 has the two-step fix (point the nameservers back to
Hostinger, then add the A record).

---

### D1.16 — `typescript@^5`, the version Next 16.3.5 scaffolds with

**Context.** TypeScript 7 is released. `create-next-app@16.3.5` scaffolds
`typescript: ^5`.

**Decision.** Keep `^5`, along with the rest of the canonical scaffold's
versions (`react` 19.2.8, `@types/node` ^20, `eslint-config-next` 16.3.5).

**Rationale.** The frontend's job in this project is to be boring. Matching the
versions the framework is tested against costs nothing here and removes a whole
class of "is it us or the toolchain?" questions. Revisit when the Next scaffold
moves.
