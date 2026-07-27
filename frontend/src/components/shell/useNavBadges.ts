'use client';

/**
 * Live nav badge counts, keyed by route href. Extracted verbatim from the old
 * Sidebar so the new rails preserve the exact same behavior and endpoints:
 *   /alerts     ← /api/inventory/summary  (out_of_stock_count)
 *   /approvals  ← /api/procurement/approvals (count)
 *   /decisions  ← /api/decisions/summary   (pending)
 *   /security   ← /api/security/kpi        (threats_active, super_admin only)
 * All are best-effort: a failed fetch simply leaves the badge hidden.
 */
import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';

export function useNavBadges(): Record<string, number> {
  const pathname = usePathname();
  const { isAuthenticated, authFetch, hasRole } = useAuth();
  const [badges, setBadges] = useState<Record<string, number>>({});

  // The /approvals and /decisions counts used to list `pathname` in their dep
  // arrays, so every single route change re-fired two uncached round-trips before
  // the next page could settle — the shell mounts once, so this cost applied to
  // every tab switch regardless of destination. Refresh on a timer instead, plus
  // whenever the user actually lands on the page a badge is for (the only place a
  // stale count is visible).
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!isAuthenticated) return;
    const id = setInterval(() => setTick((n) => n + 1), 60000);
    return () => clearInterval(id);
  }, [isAuthenticated]);

  // Collapse every unrelated route to one value so moving among them is a no-op.
  const badgeRoute =
    pathname === '/approvals' || pathname === '/decisions' ? pathname : '';
  const refreshKey = `${tick}:${badgeRoute}`;

  const set = (href: string, n: number) =>
    setBadges((prev) => (prev[href] === n ? prev : { ...prev, [href]: n }));

  // /alerts — out-of-stock count
  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    (async () => {
      try {
        const res = await authFetch('/api/inventory/summary');
        if (!res.ok) return;
        const d = await res.json();
        if (active) set('/alerts', d.out_of_stock_count ?? 0);
      } catch { /* hidden on failure */ }
    })();
    return () => { active = false; };
  }, [isAuthenticated, authFetch]);

  // /approvals — POs awaiting approval
  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    (async () => {
      try {
        const res = await authFetch('/api/procurement/approvals');
        if (!res.ok) return;
        const d = await res.json();
        if (active) set('/approvals', d.count ?? 0);
      } catch { /* hidden on failure */ }
    })();
    return () => { active = false; };
  }, [isAuthenticated, authFetch, refreshKey]);

  // /decisions — pending decisions
  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    (async () => {
      try {
        const res = await authFetch('/api/decisions/summary');
        if (!res.ok) return;
        const d = await res.json();
        if (active) set('/decisions', d.pending ?? 0);
      } catch { /* hidden on failure */ }
    })();
    return () => { active = false; };
  }, [isAuthenticated, authFetch, refreshKey]);

  // /security — active threats (super_admin only), polled
  useEffect(() => {
    if (!isAuthenticated || !hasRole(['super_admin'])) return;
    let active = true;
    const poll = async () => {
      try {
        const res = await authFetch('/api/security/kpi');
        if (!res.ok) return;
        const d = await res.json();
        if (active) set('/security', d.threats_active ?? 0);
      } catch { /* hidden on failure */ }
    };
    poll();
    const id = setInterval(poll, 30000);
    return () => { active = false; clearInterval(id); };
  }, [isAuthenticated, authFetch, hasRole]);

  return badges;
}
