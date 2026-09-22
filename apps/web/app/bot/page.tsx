import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "CompetitorTrackBot — about our crawler",
  description:
    "What CompetitorTrackBot fetches, how often, and how to stop it. The page our User-Agent points at.",
};

/**
 * The page the honest bot User-Agent advertises (§A6.2, D0.11).
 *
 * It exists because we identify ourselves: `CompetitorTrackBot/1.0
 * (+https://…/bot)`. A crawler that names itself has to be explainable, and a
 * User-Agent pointing at a 404 is worse than an anonymous one — so this page
 * ships in P1, before any scraping code exists in P3.
 *
 * Fully static: a public Server Component with no data fetching.
 */
export default function BotPage() {
  return (
    <main className="mx-auto w-full max-w-2xl px-6 py-16">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink-500">CompetitorTrack</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">About our crawler</h1>

      <p className="mt-6 text-ink-700">
        We run a small crawler so that beauty and skincare brands can see how their
        competitors&apos; prices, sales and stock change over time. It identifies itself as:
      </p>

      <pre className="mt-4 overflow-x-auto rounded-lg border border-ink-200 bg-white p-4 font-mono text-sm">
        CompetitorTrackBot/1.0
      </pre>

      <h2 className="mt-10 text-lg font-semibold">What it fetches</h2>
      <ul className="mt-3 space-y-2 text-ink-700">
        <li>
          <span className="font-mono text-sm">/robots.txt</span> — before anything else, and again
          every week.
        </li>
        <li>
          <span className="font-mono text-sm">/products.json</span> and{" "}
          <span className="font-mono text-sm">/meta.json</span> — the public endpoints a Shopify
          storefront already serves to any visitor. Optionally one collection&apos;s feed instead of
          the whole catalog.
        </li>
      </ul>
      <p className="mt-3 text-ink-700">
        That is the whole list. It never logs in, never submits a form, never adds to a cart, never
        places an order, never touches checkout, and never works around a CAPTCHA or a
        password-protected storefront.
      </p>

      <h2 className="mt-10 text-lg font-semibold">How politely</h2>
      <ul className="mt-3 space-y-2 text-ink-700">
        <li>At most one request at a time per store, never in parallel.</li>
        <li>About 2.5 seconds between requests, with jitter.</li>
        <li>A store is read roughly every six hours — a handful of requests each time.</li>
        <li>
          If a store answers <span className="font-mono text-sm">429</span>, we wait as long as its{" "}
          <span className="font-mono text-sm">Retry-After</span> header asks, and we back off
          further if it keeps refusing.
        </li>
        <li>One User-Agent, never rotated, and no attempt to look like a browser.</li>
      </ul>

      <h2 className="mt-10 text-lg font-semibold">How to stop it</h2>
      <p className="mt-3 text-ink-700">
        Add this to your <span className="font-mono text-sm">robots.txt</span>:
      </p>
      <pre className="mt-4 overflow-x-auto rounded-lg border border-ink-200 bg-white p-4 font-mono text-sm">
        {`User-agent: CompetitorTrackBot
Disallow: /`}
      </pre>
      <p className="mt-3 text-ink-700">
        We check <span className="font-mono text-sm">robots.txt</span> before adding a store and
        re-check every week, so a new rule takes effect at the next check at the latest. A store
        that disallows us is disabled on our side and stops being read. On Shopify you can edit
        these rules through <span className="font-mono text-sm">robots.txt.liquid</span> in your
        theme.
      </p>
      <p className="mt-3 text-ink-700">
        Because we identify ourselves, that rule actually works — which is the point of naming
        ourselves rather than blending in.
      </p>

      <h2 className="mt-10 text-lg font-semibold">What we store</h2>
      <p className="mt-3 text-ink-700">
        Product titles, variant titles, SKUs, prices, compare-at prices and availability, plus a
        history of changes to those values. Public catalog data, nothing about your customers, and
        no personal data of any kind.
      </p>

      <footer className="mt-12 border-t border-ink-200 pt-6 text-sm">
        <Link
          href="/"
          className="underline decoration-ink-200 underline-offset-4 hover:decoration-ink-500"
        >
          Back to CompetitorTrack
        </Link>
      </footer>
    </main>
  );
}
