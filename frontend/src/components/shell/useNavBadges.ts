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
  }, [isAuthenticated, authFetch, pathname]);

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
  }, [isAuthenticated, authFetch, pathname]);

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
