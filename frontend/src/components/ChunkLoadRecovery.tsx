'use client';

/**
 * Chunk-load recovery — prevents the "blank tab" bug after a frontend redeploy.
 *
 * Next.js code-splits per route. When a new frontend build ships, the JS chunk
 * hashes change. A browser that still has the OLD page open will, on navigating
 * to a not-yet-loaded route, request a chunk hash that no longer exists on the
 * server → `ChunkLoadError` / "Loading chunk N failed" → the route renders
 * blank. This is the classic deploy-time white screen.
 *
 * Fix (industry-standard): catch that specific error and hard-reload once so the
 * browser fetches the fresh manifest + chunks. Guarded by a sessionStorage flag
 * so a genuinely-broken chunk can't cause a reload loop — after one attempt we
 * stop and let the route error boundary (`app/error.tsx`) show its recovery UI.
 */
import { useEffect } from 'react';

const RELOAD_FLAG = 'chunkReloadAttempt';

function isChunkError(message: string): boolean {
  return (
    /ChunkLoadError/i.test(message) ||
    /Loading chunk [\w-]+ failed/i.test(message) ||
    /Loading CSS chunk/i.test(message) ||
    /Failed to fetch dynamically imported module/i.test(message) ||
    /error loading dynamically imported module/i.test(message)
  );
}

function recover() {
  try {
    if (sessionStorage.getItem(RELOAD_FLAG)) return; // already tried once — don't loop
    sessionStorage.setItem(RELOAD_FLAG, String(Date.now()));
  } catch {
    /* private mode — fall through to a single reload */
  }
  window.location.reload();
}

export default function ChunkLoadRecovery() {
  useEffect(() => {
    // Clear the guard on a clean load so future (unrelated) deploys can recover.
    try {
      const prev = sessionStorage.getItem(RELOAD_FLAG);
      // If we reloaded and the page is now healthy, drop the flag after a beat.
      if (prev) setTimeout(() => sessionStorage.removeItem(RELOAD_FLAG), 4000);
    } catch { /* ignore */ }

    const onError = (e: ErrorEvent) => {
      if (isChunkError(e.message || '')) recover();
    };
    const onRejection = (e: PromiseRejectionEvent) => {
      const msg = e.reason instanceof Error ? e.reason.message : String(e.reason ?? '');
      if (isChunkError(msg)) recover();
    };
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onRejection);
    };
  }, []);

  return null;
}
