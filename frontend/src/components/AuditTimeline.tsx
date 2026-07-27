'use client';

/**
 * Procurement audit timeline (Part III-H) — a chronological feed of procure-to-
 * pay events from the append-only audit log. Drop it on the procurement page
 * (global) or pass entityId to scope it to a single PO.
 */
import { useCallback, useEffect, useState } from 'react';
import { Card } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import {
  FilePlus2, CheckCircle2, Send, PackageCheck, Receipt, AlertTriangle, Truck, Circle,
} from 'lucide-react';

interface Event {
  id: number; event_type: string; entity_ref: string | null;
  summary: string; actor: string; created_at: string | null;
}

const ICON: Record<string, { icon: React.ReactNode; tone: string }> = {
  'po.created': { icon: <FilePlus2 className="w-4 h-4" />, tone: 'text-blue-500' },
  'po.approved': { icon: <CheckCircle2 className="w-4 h-4" />, tone: 'text-teal-500' },
  'po.sent': { icon: <Send className="w-4 h-4" />, tone: 'text-violet-500' },
  'po.received': { icon: <PackageCheck className="w-4 h-4" />, tone: 'text-teal-600' },
  'po.partially_received': { icon: <PackageCheck className="w-4 h-4" />, tone: 'text-amber-500' },
  'po.cancelled': { icon: <Circle className="w-4 h-4" />, tone: 'text-ink-muted' },
  'goods.received': { icon: <Truck className="w-4 h-4" />, tone: 'text-teal-600' },
  'invoice.recorded': { icon: <Receipt className="w-4 h-4" />, tone: 'text-violet-500' },
  'invoice.matched': { icon: <CheckCircle2 className="w-4 h-4" />, tone: 'text-teal-500' },
  'invoice.match_exception': { icon: <AlertTriangle className="w-4 h-4" />, tone: 'text-rose-500' },
  'supplier.created': { icon: <FilePlus2 className="w-4 h-4" />, tone: 'text-ink-muted' },
};

function ago(iso: string | null): string {
  if (!iso) return '';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function AuditTimeline({ entityId, limit = 20 }: { entityId?: number; limit?: number }) {
  const { authFetch } = useAuth();
  const [events, setEvents] = useState<Event[]>([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const q = entityId
        ? `?entity_type=purchase_order&entity_id=${entityId}&limit=${limit}`
        : `?limit=${limit}`;
      const res = await authFetch(`/api/procurement/events${q}`);
      if (res.ok) setEvents((await res.json()).events ?? []);
    } catch { /* ignore */ } finally { setLoaded(true); }
  }, [authFetch, entityId, limit]);
  useEffect(() => { load(); }, [load]);

  if (loaded && events.length === 0) return null;

  return (
    <Card padding="lg">
      <h3 className="text-base font-medium text-ink mb-4">Activity</h3>
      <ol className="relative border-s border-line ms-2">
        {events.map((e) => {
          const meta = ICON[e.event_type] ?? { icon: <Circle className="w-4 h-4" />, tone: 'text-ink-muted' };
          return (
            <li key={e.id} className="mb-5 ms-5">
              <span className={`absolute -start-[9px] flex items-center justify-center w-[18px] h-[18px] rounded-full bg-surface ${meta.tone}`}>
                {meta.icon}
              </span>
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-sm text-ink">{e.summary}</p>
                <span className="text-xs text-ink-muted shrink-0">{ago(e.created_at)}</span>
              </div>
              <p className="text-xs text-ink-muted mt-0.5">{e.actor}</p>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
