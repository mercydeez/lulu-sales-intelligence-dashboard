'use client';

/**
 * Approval inbox (Part III-H) — purchase orders awaiting a decision, with inline
 * approve / reject. The classic "approval inbox" workflow pattern sitting on top
 * of the procure-to-pay engine.
 */
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Inbox, Check, X, CheckCheck, Loader2 } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Button, Badge, Stagger, RevealItem } from '@/components/ui';

interface PO {
  id: number; po_number: string; status: string; total_amount: number;
  currency: string; source: string; supplier_name: string; line_count: number;
  created_at: string | null;
}
interface Inbox { count: number; total_value: number; currency: string; purchase_orders: PO[]; }

export default function ApprovalsPage() {
  const { authFetch } = useAuth();
  const [data, setData] = useState<Inbox | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/procurement/approvals');
      if (res.ok) setData(await res.json());
    } catch { /* ignore */ }
  }, [authFetch]);
  useEffect(() => { load(); }, [load]);

  const decide = async (po: PO, status: 'approved' | 'cancelled') => {
    setBusy(po.id);
    try {
      const res = await authFetch(`/api/procurement/purchase-orders/${po.id}/status`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      if (!res.ok) { const d = await res.json().catch(() => ({})); setMsg(d.message || 'Action failed'); }
      else setMsg(status === 'approved' ? `${po.po_number} approved.` : `${po.po_number} rejected.`);
      await load();
    } finally { setBusy(null); }
  };

  const approveAll = async () => {
    if (!data) return;
    for (const po of data.purchase_orders) {
      // Sequential so we surface any per-PO failure (e.g. an approval-rule cap).
      await decide(po, 'approved');
    }
  };

  const money = (n: number) => `${data?.currency ?? 'AED'} ${new Intl.NumberFormat('en-AE', { maximumFractionDigits: 0 }).format(n)}`;
  const pos = data?.purchase_orders ?? [];

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-5xl mx-auto">
        <PageHeader
          title="Approval Inbox"
          description="Purchase orders awaiting your decision."
          icon={<Inbox className="w-6 h-6" />}
          actions={pos.length > 0 ? (
            <Button variant="primary" onClick={approveAll}><CheckCheck className="w-4 h-4" /> Approve all POs</Button>
          ) : undefined}
        />

        {msg && <div className="mb-4 p-3 rounded-xl bg-teal-50 border border-teal-200 text-teal-800 text-sm">{msg}</div>}

        {data && pos.length > 0 && (
          <div className="mb-4 text-sm text-ink-muted">
            <span className="font-semibold text-ink">{data.count}</span> pending ·{' '}
            <span className="font-semibold text-ink">{money(data.total_value)}</span> at stake
          </div>
        )}

        {pos.length === 0 ? (
          <Card padding="lg">
            <div className="py-10 text-center text-ink-muted">
              <CheckCheck className="w-10 h-10 mx-auto mb-3 text-teal-400" />
              <p>Inbox zero — nothing awaiting approval.</p>
            </div>
          </Card>
        ) : (
          <Stagger className="space-y-3">
            {pos.map((po) => (
              <RevealItem key={po.id}>
              <Card padding="md" className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Link href={`/procurement/po/${po.id}`} className="font-mono text-teal-700 hover:underline">{po.po_number}</Link>
                    {po.source === 'forecast_reorder' && <Badge variant="teal">📈 forecast</Badge>}
                  </div>
                  <p className="text-sm text-ink-muted mt-0.5 truncate">
                    {po.supplier_name} · {po.line_count} lines
                  </p>
                </div>
                <div className="text-end shrink-0">
                  <p className="font-bold text-ink">{money(po.total_amount)}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Button variant="secondary" size="sm" disabled={busy === po.id} onClick={() => decide(po, 'approved')}>
                    {busy === po.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} Approve PO
                  </Button>
                  <Button variant="ghost" size="sm" disabled={busy === po.id} onClick={() => decide(po, 'cancelled')}>
                    <X className="w-4 h-4" /> Reject PO
                  </Button>
                </div>
              </Card>
              </RevealItem>
            ))}
          </Stagger>
        )}
      </div>
    </main>
  );
}
