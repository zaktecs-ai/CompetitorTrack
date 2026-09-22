# Phase 0 findings

| | |
|---|---|
| **Verdict** | ⏳ **PENDING** — awaiting the run from the production IP |
| **Store set** | 7 (6 competitors + 1 own-store stand-in) — `tools/stores_phase0.txt` |
| **Control run** | 2026-09-22, direct, browser UA, from `3.237.194.81` (AS14618 Amazon, Ashburn US) |
| **Control artifact** | `docs/phase0_results.control-dev-ip.json` |
| **Fixtures** | `tests/fixtures/phase0/<store>/` — page 1, `meta.json`, `robots.txt`, `products_limit1.json` |

> ## ⚠️ The control run is not the verdict
>
> Shopify's bot defences key off **IP reputation**. The control run below was
> executed from an **AWS datacenter IP in the build sandbox**, not from the Oracle
> Cloud A1 instance that will run production. Its store-reachability numbers
> therefore carry **no predictive weight** for the production IP, and are recorded
> only as a baseline to diff against.
>
> `GO` / `NO-GO` is decided by `tools/README_PHASE0.md` step 3, run on the server.
> Nothing in this document may be read as that verdict until this banner is
> replaced with real production numbers.

---

## 1. What the control run already settles (IP-independent)

These are properties of the **feed format and the merchants' configuration**, not of
our egress IP. They will not change when the probe is re-run from Oracle, so they
are usable now.

**Sample size, stated precisely:** 7 stores; **2,350 products** across all fetched
pages; **1,796 variants** — the variant-level field statistics below are computed
from **page 1 of each store only**, which is the page persisted as a fixture. For
the five complete-catalog stores page 1 *is* the whole catalog; for the two
over-cap stores it is the first 250 of >1,000 products. Every figure below traces
to `docs/phase0_results.control-dev-ip.json`; none is extrapolated.

### 1.1 `inventory_quantity` is NOT exposed — spec question closed

§A6.1 flagged this `[verify in-phase]`: "sources disagree on whether it is exposed."

**Observed: 0 of 1,796 variants carried an `inventory_quantity` key. Zero, across
all 7 stores.**

→ The column stays in the schema (harmless, `NULL`), and §A5's rule that it is
"informational only — never a trigger input" is confirmed as the only safe design.
Any future feature that depends on it would have nothing to read.

### 1.2 `available` is universally present — stock tracking is viable

**Observed: 1,796 of 1,796 variants carried `available`. 100% on every store.**

→ `stores.stock_tracking_enabled` (§A6.5: on when `missing_available_ratio ≤ 5%`)
will be `true` for every store in this set. The self-healing flag and the
resync-without-alerts path (§A6.6 step 4) remain necessary for stores outside it,
but the stock family is fully functional on this niche.

### 1.3 Prices are decimal strings, and zero prices exist in the wild

**Observed: all 1,796 variants had `price` as a JSON string. 0 parse failures.**

More importantly:

| Store | Variants priced `0` |
|---|---|
| fentybeauty.com | 4 |
| theinkeylist.com | 4 |
| herbivorebotanicals.com | 1 |
| saltandstone.com | 1 |
| **Total** | **10 of 1,796 (0.56%)** |

→ **The zero-price guard (§A7.3 step 1) is load-bearing, not theoretical.** Without
it, `drop_pct = (p0 − p1) / p0` divides by zero on real production data within the
first scrape of Fenty Beauty. The `suspicious_zero_price_count` admin counter will
be non-zero from day one, so its UI surface matters.

### 1.4 `compare_at_price` rates vary by two orders of magnitude

| Store | Variants with a live `compare_at` |
|---|---|
| colourpop.com | 0.8% |
| fentybeauty.com | 6.7% |
| herbivorebotanicals.com | 14.5% |
| saltandstone.com | 36.7% |
| kravebeauty.com | 48.3% |
| theinkeylist.com | 53.4% |
| versedskin.com | 69.0% |

→ Some brands run permanent "was/now" pricing. §A7.3's decision that
`SALE_START`/`SALE_END` are **flag events that ignore the threshold and the
absolute floor** is what makes this detectable — and the fact that a store can sit
at 69% "on sale" is precisely the fake-sale signal the niche wants.

### 1.5 `since_id` is ignored — `page=N` is the only pagination

**Observed: on every store probed, `?limit=250&since_id=<last id>` returned the same
head as page 1.**

→ Confirms §A6.4: the storefront feed has no cursor. `page=N` with `limit=250` is
the only scheme, and the page-repeat guard is the only defence against it
misbehaving. No page repeat was observed in this set.

### 1.6 Two of the six competitor stores exceed the 1,000-product cap ⚠️

| Store | Products seen | Completeness |
|---|---|---|
| colourpop.com | 1,000 (4 full pages) | `partial_cap_exceeded` |
| fentybeauty.com | 1,000 (4 full pages) | `partial_cap_exceeded` |
| theinkeylist.com | 137 | `complete` |
| versedskin.com | 76 | `complete` |
| herbivorebotanicals.com | 51 | `complete` |
| saltandstone.com | 46 | `complete` |
| kravebeauty.com | 40 | `complete` |

**This is a product finding, not a bug.** `MAX_PAGES=4` means a store over 1,000
products never completes a baseline and therefore **emits no variant or product
alerts at all** until the tenant scopes it to a collection (§A6.10). The two
over-cap stores are Shopify Plus brands — i.e. exactly the competitors a merchant
most wants to track.

→ Consequence for onboarding: a new tenant who adds "Fenty Beauty" as their first
competitor gets a `STORE_EXCEEDS_CAP` alert and a collection picker, **not** price
alerts. The "Over cap — track a collection instead" UI (§A6.4, §A11) is on the
critical path of the first-run experience, not an edge case. Flagged for P5.

### 1.7 Catalog shape: variants per product varies 1.0× – 11.5×

versedskin.com returned **76 products carrying 877 variants** (11.5 per product);
kravebeauty.com returned 40 products with 60 variants (1.5). The engine is
variant-level (§A7), so per-run work scales with variants, not products — worth
remembering when reading §A6.11's capacity estimate, which counts pages.

### 1.8 robots.txt allows the feed on all 7 stores

All 7 served `robots.txt` with HTTP 200 and **none** disallowed `/products.json`
for either agent token. No `Crawl-delay` was declared by any store, so
`POLITE_DELAY_SECONDS = 2.5` remains our own self-imposed politeness rather than a
merchant-stated limit.

Two candidates were **dropped** by the pre-screen:

| Dropped | Reason |
|---|---|
| youthtothepeople.com | HTTP 403 — `error_code=blocked` (also no Shopify header on `/meta.json`) |
| mytopicals.com | HTTP 404 on `/products.json` — `error_code=endpoint_disabled` |

→ Both rejections came from the classifier in §A6.3 acting exactly as specified,
which is itself a small validation of the matrix.

### 1.9 Currency coverage — and a gap

Observed: **USD ×6, GBP ×1** (theinkeylist.com). All 2-decimal currencies.

→ **No 0-decimal currency (JPY/KRW) appears in this niche sample.** §A13's required
test "a JPY `meta.json` yielding `currency_minor_unit=0`" therefore has no
real-world specimen and must be built as a synthetic `respx` fixture. Recorded so
nobody later hunts for a Japanese beauty store to satisfy it.

### 1.10 Every store sits behind Cloudflare

`server: cloudflare` on all 7. Page-1 response times were 106–403 ms.

→ Relevant to the pending question: the thing that will or won't block the Oracle IP
is a Cloudflare-fronted reputation filter, which is consistent with §A6.8's note
that a signed crawler on Oracle Cloud was still 429'd in July 2026 while the same
crawler succeeded from a residential IP.

---

## 2. What only the production run can settle

| Open question | Why the control run cannot answer it | Where it gets answered |
|---|---|---|
| Do these 7 stores return 200 from the **Oracle A1 IP**? | Pure IP reputation | README step 3 |
| Any 429 / 430, and with what `Retry-After` timings? | Same | README step 3 |
| Which User-Agent fares better — browser or honest bot? | Needs two passes ≥30 min apart from the real IP | README step 4 |
| Can the server reach `smtp.gmail.com` on 587 / 465? | Sandbox firewall permits HTTP/HTTPS only; both ports returned **INCONCLUSIVE** (TCP accepted, no `220` greeting — see D0.7) | README step 3 |
| Does `/products.json` return geo-localised prices? | Needs a foreign-country proxy; none is owned | **Stays open** — see §3 |

### Control-run SMTP result, stated honestly

```
smtp.gmail.com:587  tcp=True  tls=None  conclusive=False
smtp.gmail.com:465  tcp=True  tls=None  conclusive=False
    INCONCLUSIVE — TCP accepted but no SMTP greeting arrived.
```

This is **not** a pass and **not** a fail. The build sandbox's egress firewall
accepts the socket and drops it (`connect_ms: 0`, empty banner). Oracle Cloud blocks
outbound port 25 permanently but is documented not to block 587/465 — that
expectation is untested until the server run.

---

## 3. Residual risks observed

1. **The whole verdict rides on one unmeasured variable.** Six of seven feed checks
   are green from a datacenter IP, which is mildly encouraging — Shopify is clearly
   not blanket-blocking cloud ranges. It is *not* evidence about Oracle's ranges
   specifically, and AWS us-east-1 is about as well-reputed as datacenter IP space
   gets. Do not round this up to "it'll be fine."

2. **Geo-pricing stays unverified for the whole MVP.** Without a proxy there is no
   way to diff direct-vs-proxy prices, so §A6.5's premise is untested. The
   geo-suspect safeguard is still built and `respx`-tested, because it must exist
   *before* a proxy is ever enabled — but the empirical question is deferred, not
   answered. If a proxy is later bought, re-run README's optional pass **before**
   pointing production at it.

3. **The cap bites the most valuable competitors.** §1.6: the two Shopify Plus
   brands in the set are both over cap. Collection scoping is not a nice-to-have
   fallback; it is how large-brand tracking works at all. Any onboarding flow that
   treats it as an edge case will fail the first user who types a famous brand name.

---

## 4. Recommended environment values

Provisional — items marked ⏳ are confirmed or corrected by the production run.

| Variable | Recommended | Basis |
|---|---|---|
| `SCRAPER_PROXY_MODE` | `off` | ⏳ No proxy owned (D0.8). Becomes `on_block` only if the server run shows blocks **and** a proxy is bought. |
| `SCRAPER_PROXY_URLS` | *(empty)* | Same |
| `SCRAPER_USER_AGENT` | *(browser UA)* | ⏳ Provisional. Decided by comparing README passes 3 and 4. |
| `MAX_PAGES` | `4` | Keep. §1.6 shows the cap is reached by real stores, and raising it trades politeness for catalog size — a decision to make with data, not pre-emptively. |
| `POLITE_DELAY_SECONDS` | `2.5` | Keep. No store declared a `Crawl-delay` (§1.8), so this is our own floor. |
| `SCRAPER_CONCURRENCY` | `2` | Keep. Control run response times were 106–403 ms; the 6 h interval is nowhere near saturated. |
| `SCRAPE_INTERVAL_MINUTES` | `360` | Keep |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Unchanged; re-checked in P4 per spec |

---

## 5. How to complete this document

1. Run `tools/README_PHASE0.md` steps 3 and 4 on the Oracle A1 instance.
2. Paste both result JSONs into the build thread.
3. The ⚠️ banner at the top is replaced with the verdict; §2's table is resolved;
   §4's ⏳ rows are fixed.

Until then this document's verdict field reads **PENDING**, and it will not be
changed to anything else without production data. No number in §1 was estimated,
inferred, or filled in from expectation — every figure traces to
`docs/phase0_results.control-dev-ip.json`.
