'use client';

/**
 * Action Center (Part III-H "action cards") — turns the intelligence into the
 * next action. Surfaces forecast-driven reorder needs, pending approvals, and
 * expiry risk as one-click cards. Self-hiding when there's nothing to act on.
 */
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Zap, ShoppingCart, Inbox, Clock, ChevronRight } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { Card } from '@/components/ui';

interface Action { key: string; icon: React.ReactNode; text: string; href: string; tone: string; }

export default function ActionCenter() {
  const { authFetch, hasPermission } = useAuth();
  const [actions, setActions] = useState<Action[]>([]);

  useEffect(() => {
    if (!hasPermission('can_manage_inventory')) return;
    let active = true;
    (async () => {
      const safe = async (url: string) => { try { const r = await authFetch(url); return r.ok ? await r.json() : null; } catch { return null; } };
      const [reorder, approvals, expiry] = await Promise.all([
        safe('/api/inventory/reorder-suggestions?limit=100'),
        safe('/api/procurement/approvals'),
        safe('/api/inventory/expiry-summary'),
      ]);

      const next: Action[] = [];
      if (reorder?.count > 0) next.push({
        key: 'reorder', icon: <ShoppingCart className="w-5 h-5" />,
        text: `${reorder.count} item${reorder.count > 1 ? 's' : ''} need reordering`,
        href: '/procurement', tone: 'text-coral-600',
      });
      if (approvals?.count > 0) next.push({
        key: 'approvals', icon: <Inbox className="w-5 h-5" />,
        text: `${approvals.count} PO${approvals.count > 1 ? 's' : ''} awaiting approval`,
        href: '/approvals', tone: 'text-teal-600',
      });
      const expiringSoon = (expiry?.expiring_7_days ?? 0) + (expiry?.expired_batches ?? 0);
      if (expiringSoon > 0) next.push({
        key: 'expiry', icon: <Clock className="w-5 h-5" />,
        text: `${expiringSoon} batch${expiringSoon > 1 ? 'es' : ''} expired or expiring this week`,
        href: '/inventory', tone: 'text-amber-600',
      });

      if (active) setActions(next);
    })();
    return () => { active = false; };
  }, [authFetch, hasPermission]);

  if (actions.length === 0) return null;

  return (
    <Card padding="lg" className="mb-6 border border-coral-100">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="w-5 h-5 text-coral-500" />
        <h3 className="text-base font-medium text-ink">Action Center</h3>
      </div>
      <div className="space-y-2">
        {actions.map((a) => (
          <Link key={a.key} href={a.href}
            className="flex items-center gap-3 p-3 rounded-xl hover:bg-[#faf3ee] transition-colors group">
            <span className={a.tone}>{a.icon}</span>
            <span className="flex-1 text-sm text-ink">{a.text}</span>
            <ChevronRight className="w-4 h-4 text-ink-muted group-hover:translate-x-0.5 transition-transform" />
          </Link>
        ))}
      </div>
    </Card>
  );
}
