"""Scraper package — implementation lands in P3.

This package exists in P1 to fix one thing early: **one success contract per
endpoint**, which is decision D0.9.

The Phase 0 probe shipped a single `classify()` applied to every endpoint it
read, so `/robots.txt` (text) and `/meta.json` (JSON without a `products` key)
were both recorded as `endpoint_disabled` on all seven stores while actually
returning healthy 200s. No decision changed — the downstream code branched on
`status` — but the artifact looked like every store failed two of three
fetches, which invites the whole dataset to be dismissed.

So the response matrix of §A6.3 is the **feed** classifier and nothing else.
P3 adds three separate modules, and no shared "classify any response" helper:

    classify_feed.py     200 + parseable JSON + a `products` key   (§A6.3)
    classify_meta.py     200 + parseable JSON of any shape         (§A6.9 step 4)
    classify_robots.py   200 with a non-empty body; 4xx = no rules stated,
                         5xx or transport failure = disallow-all    (D0.5)

A future contributor who wants one generic classifier is re-introducing the
Phase 0 defect. Don't.
"""
