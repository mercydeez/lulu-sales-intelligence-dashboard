'use client';

/**
 * Approval inbox (Part III-H) — purchase orders awaiting a decision, with inline
 * approve / reject. The classic "approval inbox" workflow pattern sitting on top
 * of the procure-to-pay engine.
 */
import { useState } from 'react';
import Link from 'next/link';
import { Inbox, Check, X, CheckCheck, Loader2, TrendingUp } from 'lucide-react';
import { PageHeader, Card, Button, Badge, Stagger, RevealItem } from '@/components/ui';
import { useApprovalInbox, useDecidePO, type PO } from '@/lib/queries/procurement';

export default function ApprovalsPage() {
  const [msg, setMsg] = useState('');
  const { data } = useApprovalInbox();
  const decidePO = useDecidePO();
  // Per-PO spinner: the mutation is single-flight, so the row being decided is
  // the one whose id matches the in-flight variables.
  const busy = decidePO.isPending ? decidePO.variables?.id ?? null : null;

  const decide = async (po: PO, status: 'approved' | 'cancelled') => {
    try {
      await decidePO.mutateAsync({ id: po.id, status });
      setMsg(status === 'approved' ? `${po.po_number} approved.` : `${po.po_number} rejected.`);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'Action failed');
    }
  };

  const approveAll = async () => {
    if (!data) return;
    for (const po of data.purchase_orders) {
      // Sequential so we surface any per-PO failure (e.g. an approval-rule cap).
      await decide(po, 'approved');
    }
  };

  const money = (n: number) => `${data?.currency ?? 'AED'} ${new Intl.NumberFormat('en-AE', { maximumFractionDigits: 0 }).format(n)}`;
  const pos: PO[] = data?.purchase_orders ?? [];

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
                    {po.source === 'forecast_reorder' && (
                      <Badge variant="teal">
                        <TrendingUp className="h-3 w-3" aria-hidden /> forecast
                      </Badge>
                    )}
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
