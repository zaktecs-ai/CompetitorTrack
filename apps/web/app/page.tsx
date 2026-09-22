import Link from "next/link";

import { HealthPanel } from "./health-panel";

/**
 * Placeholder dashboard (P1). A Server Component that renders a shell and never
 * calls the API — all data comes from the client component below (§A11).
 *
 * The real dashboard (competitor cards, alerts, digest banner) arrives in P5.
 */
export default function Home() {
  return (
    <main className="mx-auto flex min-h-full w-full max-w-2xl flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink-500">
          CompetitorTrack · P1 skeleton
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">System health</h1>
        <p className="text-sm text-ink-700">
          Shopify price, sale, stock and catalog tracking for beauty and skincare brands. The
          dashboard lands in P5; this page exists to prove the stack end to end — browser to Caddy
          to FastAPI to PostgreSQL, plus the scheduler&apos;s heartbeat.
        </p>
      </header>

      <section className="rounded-xl border border-ink-200 bg-white p-6 shadow-sm">
        <HealthPanel />
      </section>

      <footer className="text-xs text-ink-500">
        <Link
          href="/bot"
          className="underline decoration-ink-200 underline-offset-4 hover:decoration-ink-500"
        >
          About our crawler
        </Link>
      </footer>
    </main>
  );
}
