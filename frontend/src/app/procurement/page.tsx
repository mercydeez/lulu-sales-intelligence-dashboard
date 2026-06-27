'use client';

/**
 * Procurement (Part III-E) — the "system of action" UI. Turns the forecast
 * reorder signal into purchase orders: one click generates auto-grouped draft
 * POs per supplier, then each PO flows through approval → sent → received.
 */
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Truck, Sparkles, Loader2, CheckCircle2 } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Button, Badge } from '@/components/ui';
import AuditTimeline from '@/components/AuditTimeline';
import type { BadgeVariant } from '@/components/ui';

interface Supplier { id: number; name: string; catalog_items: number; lead_time_days: number; status: string; }
interface PO {
  id: number; po_number: string; status: string; total_amount: number; currency: string;
  source: string; supplier_name: string; line_count: number; created_at: string | null;
}

const STATUS_BADGE: Record<string, BadgeVariant> = {
  draft: 'neutral', pending_approval: 'amber', approved: 'teal',
  sent: 'violet', partially_received: 'amber', received: 'success', cancelled: 'danger',
};

// The next action from each status. 'receive' records a goods receipt for all
// outstanding lines; 'status' is a plain lifecycle transition.
type NextAction = { label: string; kind: 'status' | 'receive'; status?: string };
const NEXT_ACTION: Record<string, NextAction | undefined> = {
  draft: { label: 'Approve', kind: 'status', status: 'approved' },
  approved: { label: 'Mark sent', kind: 'status', status: 'sent' },
  sent: { label: 'Receive', kind: 'receive' },
  partially_received: { label: 'Receive rest', kind: 'receive' },
};

export default function ProcurementPage() {
  const { authFetch } = useAuth();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [pos, setPos] = useState<PO[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    try {
      const [sRes, pRes] = await Promise.all([
        authFetch('/api/procurement/suppliers'),
        authFetch('/api/procurement/purchase-orders'),
      ]);
      if (sRes.ok) setSuppliers((await sRes.json()).suppliers ?? []);
      if (pRes.ok) setPos((await pRes.json()).purchase_orders ?? []);
    } catch { /* leave empty */ } finally { setLoading(false); }
  }, [authFetch]);

  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setGenerating(true);
    setMessage('');
    try {
      const res = await authFetch('/api/procurement/purchase-orders/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lead_time_days: 7, cover_target_days: 7 }),
      });
      const data = await res.json();
      setMessage(res.ok ? data.message : (data.message || 'Generation failed'));
      await load();
    } catch { setMessage('Generation failed'); } finally { setGenerating(false); }
  };

  const advance = async (po: PO, action: NextAction) => {
    const url = action.kind === 'receive'
      ? `/api/procurement/purchase-orders/${po.id}/receive`
      : `/api/procurement/purchase-orders/${po.id}/status`;
    const body = action.kind === 'receive' ? {} : { status: action.status };
    const res = await authFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setMessage(d.message || 'Action failed');
    }
    await load();
  };

  const fmt = (n: number) => new Intl.NumberFormat('en-AE', { maximumFractionDigits: 0 }).format(n);
  const draftCount = pos.filter((p) => p.status === 'draft').length;

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title="Procurement"
          description="Forecast-driven purchase orders — from reorder signal to approved order."
          icon={<Truck className="w-6 h-6" />}
          actions={
            <Button variant="primary" onClick={generate} disabled={generating}>
              {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              Generate from forecast
            </Button>
          }
        />

        {message && (
          <div className="mb-4 p-3 rounded-xl bg-teal-50 border border-teal-200 text-teal-800 text-sm flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4" /> {message}
          </div>
        )}

        {/* Suppliers */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          {suppliers.map((s) => (
            <Card key={s.id} padding="md">
              <p className="font-semibold text-ink">{s.name}</p>
              <p className="text-sm text-ink-muted mt-1">
                {s.catalog_items} catalog items · {s.lead_time_days}-day lead
              </p>
            </Card>
          ))}
          {!loading && suppliers.length === 0 && (
            <p className="text-ink-muted text-sm">No suppliers yet.</p>
          )}
        </div>

        {/* Purchase orders */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-base font-medium text-ink">Purchase Orders</h3>
            <span className="text-sm text-ink-muted">{draftCount} draft · {pos.length} total</span>
          </div>

          {loading ? (
            <div className="h-24 animate-pulse rounded-lg bg-ink/5" />
          ) : pos.length === 0 ? (
            <p className="text-ink-muted text-sm py-6 text-center">
              No purchase orders yet — click <span className="font-medium">Generate from forecast</span> to create them.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-start text-ink-muted border-b border-line">
                    <th className="py-2 pe-4 font-medium">PO</th>
                    <th className="py-2 pe-4 font-medium">Supplier</th>
                    <th className="py-2 pe-4 font-medium">Status</th>
                    <th className="py-2 pe-4 font-medium text-end">Lines</th>
                    <th className="py-2 pe-4 font-medium text-end">Total (AED)</th>
                    <th className="py-2 font-medium text-end">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {pos.map((po) => {
                    const next = NEXT_ACTION[po.status];
                    return (
                      <tr key={po.id} className="border-b border-line/60">
                        <td className="py-2.5 pe-4 font-mono">
                          <Link href={`/procurement/po/${po.id}`} className="text-teal-700 hover:underline">{po.po_number}</Link>
                        </td>
                        <td className="py-2.5 pe-4 text-ink">{po.supplier_name}</td>
                        <td className="py-2.5 pe-4">
                          <Badge variant={STATUS_BADGE[po.status] ?? 'neutral'}>
                            {po.status.replace('_', ' ')}
                          </Badge>
                          {po.source === 'forecast_reorder' && (
                            <span className="ms-2 text-[10px] text-ink-muted">📈 forecast</span>
                          )}
                        </td>
                        <td className="py-2.5 pe-4 text-end text-ink">{po.line_count}</td>
                        <td className="py-2.5 pe-4 text-end font-medium text-ink">{fmt(po.total_amount)}</td>
                        <td className="py-2.5 text-end">
                          {next ? (
                            <Button variant="secondary" size="sm" onClick={() => advance(po, next)}>
                              {next.label}
                            </Button>
                          ) : (
                            <span className="text-ink-muted text-xs">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="mt-6">
          <AuditTimeline limit={20} />
        </div>
      </div>
    </main>
  );
}
