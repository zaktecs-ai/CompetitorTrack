# Phase 0 findings

| | |
|---|---|
| **Verdict** | ✅ **GO** — direct egress, no proxy required |
| **Decided by** | Two full passes on the production server, 2026-09-22 |
| **Production host** | Oracle Cloud A1, `130.61.153.125`, **AS31898 Oracle Corporation, Frankfurt (DE)**, aarch64, Python 3.12.3 |
| **Result** | **7 / 7 stores** returned HTTP 200 + valid JSON **directly**, on **both** User-Agent passes. 0 blocked, 0 rate-limited, 0 robots-disallowed. |
| **Threshold** | ≥5 of 6 competitor stores. Achieved **6 of 6** (plus the own-store stand-in). |
| **Recommended `SCRAPER_PROXY_MODE`** | `off` |
| **Recommended `SCRAPER_USER_AGENT`** | the honest bot UA — see §4 |
| **SMTP** | `smtp.gmail.com` **587 (STARTTLS) and 465 (implicit) both reachable**, TLSv1.3, valid `220` greetings |
| Evidence | `docs/phase0_evidence.production.md` · control run: `docs/phase0_results.control-dev-ip.json` |

---

## 1. Verdict detail

| Store | Tier | Currency | Products | Variants (p1) | Completeness | Browser UA | Bot UA |
|---|---|---|---|---|---|---|---|
| colourpop.com | large | USD | 1,000+ | 250 | `partial_cap_exceeded` | ✅ 200 | ✅ 200 |
| fentybeauty.com | large | USD | 1,000+ | 254 | `partial_cap_exceeded` | ✅ 200 | ✅ 200 |
| theinkeylist.com | medium | **GBP** | 137 | 146 | `complete` | ✅ 200 | ✅ 200 |
| kravebeauty.com | medium | USD | 40 | 60 | `complete` | ✅ 200 | ✅ 200 |
| herbivorebotanicals.com | small | USD | 51 | 62 | `complete` | ✅ 200 | ✅ 200 |
| saltandstone.com | small | USD | 46 | 147 | `complete` | ✅ 200 | ✅ 200 |
| versedskin.com *(own-store stand-in)* | small | USD | 76 | 877 | `complete` | ✅ 200 | ✅ 200 |

All 7 served by **Cloudflare** with `powered-by: Shopify`. Page-1 latency from Frankfurt: **101–624 ms**.

**The core MVP risk is now retired.** §A15's K1 — "Oracle datacenter IP vs Shopify's 2026 bot limits" — was the single largest unmeasured variable in the whole plan. It is measured, and the answer is that this Oracle A1 IP is not blocked by any store in the set. Phases 1–6 may proceed on the zero-new-monthly-spend assumption.

### A rate-limit stress test we got by accident

The README asked for a **30-minute gap** between the two UA passes, so that pass 1's rate-limit state could not pollute pass 2's result. The passes were actually run **~5 minutes apart** (07:10:08 and 07:14:55 UTC).

This deviation does not weaken the conclusion — it strengthens it. Roughly **120 requests across 7 domains inside 5 minutes from a single datacenter IP produced zero 429s and zero 430s.** Had pass 1 provoked any throttling, pass 2 would have shown it. Nothing appeared, so the "which UA fares better" comparison is valid *and* we have evidence that the politeness budget has real headroom above `POLITE_DELAY_SECONDS = 2.5`.

---

## 2. ⭐ Geo-pricing: answered, without a proxy

§A6.5 carried a `[verify in-phase]` marker: *does `/products.json` return geo-localised prices?* The plan was to diff direct-vs-proxy responses — impossible, since no proxy is owned.

It got answered anyway. Two independent runs exist from **two continents**:

| | Control run | Production run |
|---|---|---|
| Egress | `3.237.194.81` — AS14618 Amazon, **Ashburn, US** | `130.61.153.125` — AS31898 Oracle, **Frankfurt, DE** |
| When (UTC) | 06:58:49 | 07:14:55 |

Comparing the **page-1 response size in bytes** for every store:

| Store | US (Ashburn) | DE (Frankfurt) | Identical |
|---|---|---|---|
| colourpop.com | 1,036,897 | 1,036,897 | ✅ |
| fentybeauty.com | 1,199,231 | 1,199,231 | ✅ |
| theinkeylist.com | 836,467 | 836,467 | ✅ |
| kravebeauty.com | 229,258 | 229,258 | ✅ |
| herbivorebotanicals.com | 159,735 | 159,735 | ✅ |
| saltandstone.com | 275,832 | 275,832 | ✅ |
| versedskin.com | 842,236 | 842,236 | ✅ |

**All seven responses are byte-identical across the Atlantic**, 16 minutes apart. Byte-identical is a stronger statement than "same prices": it means same currency, same product ordering, same `compare_at_price` values, same everything. Every derived statistic agreed too — variant counts, `compare_at` rates and zero-price counts matched exactly on all 7 stores.

**Two useful consequences:**

1. `/products.json` is **not** geo-localised for these stores, consistent with the spec's note that localisation is documented for the Storefront GraphQL API and `/products/<handle>.js` but not for this endpoint.
2. **The fixtures already committed in `tests/fixtures/phase0/` are bit-for-bit what the production server receives.** They were captured from the control IP, and that is now a verified non-issue rather than a caveat.

**What this does not prove.** Two datacenter IPs in US-East and EU-Central is not a test of every market. A store with Shopify Markets multi-currency configured could still localise, and a residential IP in a market with its own storefront might see something different. **§A6.5's geo-suspect safeguard therefore stays in the build** — it costs nothing while `SCRAPER_PROXY_MODE=off` (transport never changes, so the rule can never fire) and it is the only thing standing between a future proxy purchase and a store-wide false PRICE_DROP storm.

---

## 3. Settled facts about the feed

Sample: 7 stores, **2,350 products** across fetched pages, **1,796 variants** on page 1. Variant-level statistics are page-1 only; for the 5 complete-catalog stores page 1 *is* the whole catalog.

### 3.1 `inventory_quantity` is not exposed — spec question closed
**0 of 1,796 variants** carried the key. Zero, on every store, on both passes. §A5's rule that it is "informational only — never a trigger input" is confirmed as the only safe design; the column will always be `NULL`.

### 3.2 `available` is universally present
**1,796 of 1,796.** `stores.stock_tracking_enabled` will be `true` across the set. The self-healing flag and the silent-resync path (§A6.6 step 4) stay for stores outside it, but the stock family is fully functional in this niche.

### 3.3 Prices are decimal strings, and zero prices are real
All 1,796 variants had `price` as a JSON **string**; **0 parse failures**.

| Store | Variants priced `0` (page 1) |
|---|---|
| fentybeauty.com | 4 |
| theinkeylist.com | 4 |
| herbivorebotanicals.com | 1 |
| saltandstone.com | 1 |
| **Total** | **10 of 1,796 (0.56%)** |

Fenty page 2 carried 5 more. **The zero-price guard (§A7.3 step 1) is load-bearing on real production data** — without it, `drop_pct = (p0 − p1) / p0` divides by zero on the first Fenty Beauty scrape. `suspicious_zero_price_count` will be non-zero from day one, so its admin surface matters.

### 3.4 `compare_at_price` live-rates span two orders of magnitude

| Store | Live `compare_at` |
|---|---|
| colourpop.com | 0.8% |
| fentybeauty.com | 6.7% |
| herbivorebotanicals.com | 14.5% |
| saltandstone.com | 36.7% |
| kravebeauty.com | 48.3% |
| theinkeylist.com | 53.4% |
| versedskin.com | **69.0%** |

A brand sitting at 69% "on sale" is exactly the permanent-discount signal this niche exists to expose, and it is only detectable because §A7.3 makes `SALE_START`/`SALE_END` **flag events that ignore the threshold and the absolute floor**.

Within one store the rate also moves per page — Fenty ran 6.7% / 2.3% / 35.5% / 16.8% across pages 1–4 — because the feed is ordered newest-first and older lines discount harder. Worth knowing before anyone reads a single page as representative of a catalog.

### 3.5 `since_id` is ignored — `page=N` is the only pagination
On all 7 stores, `?limit=250&since_id=<id>` returned the **same head as page 1**. Confirms §A6.4: there is no cursor, so the page-repeat guard is the only defence against `page=N` misbehaving. No page repeat was observed in this set.

### 3.6 ⚠️ Two of six competitor stores exceed the 1,000-product cap

ColourPop and Fenty Beauty both returned 4 full pages of 250 with no empty page. Per §A6.4 that is `partial_cap_exceeded`: such a store **never completes a baseline and therefore emits no variant or product alerts at all** until the tenant scopes it to a collection.

Both are Shopify Plus brands — i.e. exactly the competitors a merchant most wants to track. **A new tenant who types "Fenty Beauty" as their first competitor gets a `STORE_EXCEEDS_CAP` alert and a collection picker, not price alerts.** The "Over cap — track a collection instead" flow (§A6.4, §A11) sits on the critical path of the first-run experience, not in the edge cases. Flagged for P5.

### 3.7 Same-domain redirects are real — correcting an earlier note

An earlier draft of this document claimed the `www.` redirect case had no real-world specimen. **That was wrong.** The production run recorded three same-domain 301s:

| Store | Redirect observed |
|---|---|
| herbivorebotanicals.com | `/robots.txt` → 301 → `www.herbivorebotanicals.com/robots.txt` |
| saltandstone.com | `/robots.txt` → 301 → `www.saltandstone.com/robots.txt` |
| theinkeylist.com | `/robots.txt` → 301 → `uk.theinkeylist.com/robots.txt` |

The probe's registrable-domain check classified all three as same-domain, followed one hop, and evaluated the correct rules. So **the redirect-follow path of §A6.3 is exercised by real data and works.**

Two notes that matter for the build:

- **The feed itself never redirected** on any store — 0 hops on all 7 `/products.json` requests, and the `www.` variant of every domain served the feed directly with 200. So §A13's specific test *"www redirect followed and `domain` persisted"* still needs a `respx` mock, because it asserts on the **feed** endpoint and on persisting `stores.domain`.
- **`robots.txt` and the feed can canonicalise to different hosts.** On saltandstone.com, robots lives at `www.` while the feed serves from the apex without redirect. Following the robots redirect is correct (same store, same rules), but nobody should assume one final host serves both.

`theinkeylist.com` is the sharpest case: the apex robots redirect lands on `uk.theinkeylist.com`, and `/meta.json` reports `currency: GBP`, `country: GB`, `name: "INKEY UK"`. The **US control run reported the identical values**, so this is the apex genuinely being the UK storefront — not geo-routing.

### 3.8 robots.txt allows the feed on all 7, under both agent tokens
All 7 served `robots.txt` with HTTP 200. None disallowed `/products.json` — checked as agent token `mozilla` in pass 1 and `competitortrackbot` in pass 2. **No store declared a `Crawl-delay`**, so `POLITE_DELAY_SECONDS = 2.5` is our own self-imposed floor, not a merchant-stated limit.

Two candidates were dropped by the pre-screen, both by the §A6.3 classifier behaving exactly as specified:

| Dropped | Reason |
|---|---|
| youthtothepeople.com | HTTP 403 → `blocked` |
| mytopicals.com | HTTP 404 on `/products.json` → `endpoint_disabled` |

Reserves, all `feed_ok`: `glossier.com`, `kyliecosmetics.com`, `necessaire.com`.

### 3.9 Currency coverage — and a gap
USD ×6, GBP ×1. All 2-decimal. **No 0-decimal currency (JPY/KRW) exists in this niche sample**, so §A13's required test *"a JPY `meta.json` yielding `currency_minor_unit=0`"* has no real specimen and must be a synthetic `respx` fixture. Recorded so nobody hunts for a Japanese beauty store to satisfy it.

### 3.10 Catalog shape varies 1.0×–11.5× variants per product
versedskin.com: 76 products / **877 variants** (11.5×). kravebeauty.com: 40 / 60 (1.5×). The engine is variant-level, so per-run work scales with **variants**, not products — relevant when reading §A6.11's capacity estimate, which counts pages.

---

## 4. User-Agent recommendation: the honest bot UA

Both passes returned **7/7, zero blocks, zero 429s**. Neither UA was penalised, so the choice is not forced by access — which means it should be made on merit.

**Recommendation: `CompetitorTrackBot/1.0 (+{PUBLIC_ORIGIN}/bot)`.**

| | Honest bot UA | Browser UA |
|---|---|---|
| Measured access on this set | 7/7 | 7/7 |
| robots.txt verdict | allowed as `competitortrackbot` (verified in pass 2) | allowed as `mozilla` |
| Defensible if a merchant asks who we are | yes — `/bot` page explains the crawler | no |
| Prerequisite for Web Bot Auth (§A6.8) and its higher Shopify limits | yes | no |
| Merchants can opt out of us specifically | **yes** | no |

That last row is the real trade-off, and it is a business decision rather than a technical one: an identified crawler can be blocked by name in `robots.txt`, and we would honour it (§A6.8). The browser UA avoids that by being indistinguishable from a person — which is precisely why it is not defensible. Since the honest UA costs **zero measured access** today and is the only path to Shopify's higher signed-bot limits, it is the right default. Revisit only if a material number of target stores begin disallowing the token.

---

## 5. Residual risks

1. **The cap bites the most valuable competitors.** §3.6. Collection scoping is not a fallback for awkward stores; it is how large-brand tracking works at all. Any onboarding flow that treats it as an edge case fails the first user who types a famous brand name.
2. **Geo-pricing is measured low-risk, not zero-risk.** §2. Two datacenter IPs in US/EU is not every market, and a Shopify Markets store could still localise. The safeguard stays; if a proxy is ever bought, run the optional proxy pass **before** pointing production at it.
3. **Today's access is not a guarantee of tomorrow's.** Shopify tightened limits for unsigned bots in May 2026 and can do so again; individual merchants can add `Disallow: /products.json` at any time. §A6.8's weekly robots re-check and the `blocked`/`rate_limited` back-off exist for exactly this, and `docs/WEB_BOT_AUTH.md` remains the documented free escalation path.
4. **Frankfurt is an EU region reading mostly US storefronts.** Latency is fine (101–624 ms) and pricing is unaffected (§2), but `tenants.timezone` defaults and any future data-residency claim should be written knowing where the box actually sits.
5. **One store's identity is locale-flavoured.** `theinkeylist.com` resolves to the UK storefront in GBP. A tenant expecting the US INKEY catalog would be tracking the wrong prices. §A6.9 step 4 persists whatever `/meta.json` reports, which is correct — but the UI must show the store's currency prominently so a tenant notices.

---

## 6. Recommended environment values

All rows are now decided by measurement rather than provisional.

| Variable | Value | Basis |
|---|---|---|
| `SCRAPER_PROXY_MODE` | `off` | 7/7 direct. No proxy needed, none owned. §1 |
| `SCRAPER_PROXY_URLS` | *(empty)* | Same |
| `SCRAPER_USER_AGENT` | `CompetitorTrackBot/1.0 (+{PUBLIC_ORIGIN}/bot)` | Zero measured access cost, defensible, Web-Bot-Auth-ready. §4 |
| `MAX_PAGES` | `4` | Keep. Raising it trades politeness for catalog size; §3.6 says the fix for big stores is collection scoping, not more pages. |
| `POLITE_DELAY_SECONDS` | `2.5` | Keep. No store declared a `Crawl-delay`, and §1 shows headroom — but headroom is not a reason to spend it. |
| `SCRAPER_CONCURRENCY` | `2` | Keep. 101–624 ms responses; the 6 h interval is nowhere near saturated. |
| `SCRAPE_INTERVAL_MINUTES` | `360` | Keep |
| `PLATFORM_SMTP_URL` | `smtp+starttls://…@smtp.gmail.com:587` | 587 and 465 both verified reachable with TLSv1.3. 587/STARTTLS is the spec default. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Unchanged; re-checked in P4 per spec |
| `RUN_STALE_MINUTES`, `DIGEST_TICK_MINUTES` | `30`, `15` | Unchanged; nothing in P0 bears on them |

---

## 7. Provenance

Every figure in this document traces to a probe run:

- **Production** — `docs/phase0_evidence.production.md` holds the verbatim console summaries of both passes plus the `run` / `egress` / `smtp` / `summary` blocks of the bot pass. The full raw JSONs remain on the server at `~/CompetitorTrack/phase0_results.{browser,bot}.json`.
- **Control** — `docs/phase0_results.control-dev-ip.json`, complete and committed. Used only for the cross-continent comparison in §2, and labelled as a control everywhere it appears.
- **Fixtures** — `tests/fixtures/phase0/`, captured on the control IP and **verified byte-identical to the production responses** (§2).

Nothing was estimated, inferred, or filled in from expectation. The verdict field read `PENDING` until the production numbers existed.
