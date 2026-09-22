"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

/**
 * Every authenticated request in this app is made from the browser through
 * TanStack Query (§A11). Server Components render shells and never call the API,
 * so there is no server-side query client and nothing to hydrate.
 *
 * The client is created in state rather than at module scope: a module-level
 * client would be shared across requests in the Node server and leak one user's
 * cache into another's render.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
