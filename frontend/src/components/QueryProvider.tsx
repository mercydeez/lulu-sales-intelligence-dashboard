'use client';

/**
 * TanStack Query provider — the reactive data layer.
 *
 * WHY: 40+ pages hand-rolled `useEffect`+loading+error over the fetch-only cache
 * in lib/apiClient.ts. TanStack Query adds request dedup, stale-while-revalidate,
 * background refetch, and mutation-driven cache invalidation on top — while
 * `lib/apiClient.ts` stays the transport (CSRF, httpOnly-cookie auth, single-
 * flight 401→refresh, its own authorization-scoped TTL micro-cache). Pages
 * migrate to `lib/queries/*` hooks incrementally; nothing here forces a rewrite.
 *
 * Defaults are tuned for an analytics dashboard: data is fresh for 30s (most
 * KPIs update on a minutes cadence), retries once (the transport already retries
 * auth), and refetch-on-window-focus is ON so a returning operator sees current
 * numbers without a manual refresh.
 */
import { ReactNode, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

export default function QueryProvider({ children }: { children: ReactNode }) {
  // One client per browser session (useState initializer avoids re-creating it on
  // every render and keeps it out of module scope so SSR never shares a client).
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            retry: 1,
            refetchOnWindowFocus: true,
          },
          mutations: { retry: 0 },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
