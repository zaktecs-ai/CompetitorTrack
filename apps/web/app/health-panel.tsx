"use client";

import { useQuery } from "@tanstack/react-query";

/**
 * The P1 placeholder dashboard: a client component that reads `/api/health`
 * (§A11's Definition of Done). Same-origin, because Caddy routes `/api/*` to
 * FastAPI and everything else here — so no base URL, no CORS, no env var.
 *
 * `/api/health` answers **503** when the scheduler heartbeat is stale, with a
 * body that explains which part is unhealthy. So the response is read on every
 * status code and `fetch` is never treated as "failed" just because the status
 * was not 2xx — that distinction is the whole point of the endpoint.
 *
 * The full fetch wrapper (credentials, CSRF header, single-flight refresh)
 * arrives with auth in P5. This deliberately stays a plain fetch.
 */

type HealthPayload = {
  api: string;
  db: string;
  scheduler: string;
  heartbeat_age_s: number | null;
  heartbeat_max_age_s: number;
};

type HealthResult = {
  status: number;
  body: HealthPayload;
};

async function fetchHealth(): Promise<HealthResult> {
  const response = await fetch("/api/health", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  const body = (await response.json()) as HealthPayload;
  return { status: response.status, body };
}

const TONE: Record<string, string> = {
  ok: "text-ok",
  error: "text-bad",
  stale: "text-bad",
  unknown: "text-warn",
};

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink-200 py-3 last:border-b-0">
      <span className="font-mono text-sm text-ink-700">{label}</span>
      <span className={`font-mono text-sm font-medium ${TONE[value] ?? "text-ink-950"}`}>
        {value}
      </span>
    </div>
  );
}

export function HealthPanel() {
  const { data, isPending, isError, refetch, isFetching } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  });

  if (isPending) {
    // Skeleton, not a spinner (§A11).
    return (
      <div className="animate-pulse space-y-3" aria-busy="true" aria-label="Loading health">
        <div className="h-4 w-1/3 rounded bg-ink-200" />
        <div className="h-4 w-1/2 rounded bg-ink-200" />
        <div className="h-4 w-2/5 rounded bg-ink-200" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-bad">
          Could not reach the API. Is the <code className="font-mono">api</code> container running?
        </p>
        <button
          type="button"
          onClick={() => refetch()}
          className="min-h-11 rounded-md border border-ink-200 px-4 text-sm font-medium hover:bg-white"
        >
          Try again
        </button>
      </div>
    );
  }

  const { status, body } = data;
  const age = body.heartbeat_age_s;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-4">
        <span
          className={`font-mono text-xs uppercase tracking-wider ${
            status === 200 ? "text-ok" : "text-bad"
          }`}
        >
          HTTP {status}
          {status === 200 ? " — healthy" : " — degraded"}
        </span>
        <span className="font-mono text-xs text-ink-500">
          {isFetching ? "refreshing…" : "refreshes every 30s"}
        </span>
      </div>

      <Row label="api" value={body.api} />
      <Row label="db" value={body.db} />
      <Row label="scheduler" value={body.scheduler} />
      <Row
        label="heartbeat_age_s"
        value={age === null ? "never" : `${age} / ${body.heartbeat_max_age_s}`}
      />

      {body.scheduler !== "ok" && (
        <p className="mt-4 text-sm text-ink-700">
          The scheduler owns every background job — scraping and digests. While it is{" "}
          <span className="font-mono">{body.scheduler}</span>, nothing is being scraped, which is
          why this endpoint reports 503 even though the page loads.
        </p>
      )}
    </div>
  );
}
