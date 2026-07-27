'use client';

/**
 * Purchase Order — the END of the reorder workflow. When you arrive from a
 * "X will run out" decision (?item=X), the line for X is highlighted and scrolled
 * to, so the item you came to act on is never lost. Review and Approve happen on
 * THIS page — no bouncing to another screen to approve.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { Printer, ArrowLeft, CheckCircle2, Check, TrendingUp } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/components/ui';
import { PRODUCT_NAME } from '@/lib/brand';
import AuditTimeline from '@/components/AuditTimeline';

interface POLine { id: number; item_name: string; quantity: number; unit_cost: number; line_total: number; received_qty: number; }
interface PODetail {
  id: number; po_number: string; status: string; supplier_name: string;
  total_amount: number; currency: string; source: string;
  created_at: string | null; approved_at: string | null;
  lines: POLine[]; receipts: { receipt_number: string; status: string }[];
}

export default function PurchaseOrderPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const { authFetch } = useAuth();
  const { show } = useToast();
  const focusItem = search.get('item');   // the item you came here to act on
  const [po, setPo] = useState<PODetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [approving, setApproving] = useState(false);
  const rowRef = useRef<HTMLTableRowElement | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`/api/procurement/purchase-orders/${id}`);
      if (res.ok) setPo(await res.json()); else setNotFound(true);
    } catch { setNotFound(true); }
  }, [authFetch, id]);
  useEffect(() => { load(); }, [load]);

  // Scroll the item you came for into view once the PO loads.
  useEffect(() => {
    if (po && focusItem && rowRef.current) {
      rowRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [po, focusItem]);

  const money = (n: number) => `${po?.currency ?? 'AED'} ${new Intl.NumberFormat('en-AE', { minimumFractionDigits: 2 }).format(n)}`;
  const fmtDate = (s: string | null) => (s ? new Date(s).toLocaleDateString('en-AE', { year: 'numeric', month: 'short', day: 'numeric' }) : '—');
  const isMatch = (name: string) => !!focusItem && name.trim().toLowerCase() === focusItem.trim().toLowerCase();
  const canApprove = po && (po.status === 'draft' || po.status === 'pending_approval');

  const approve = async () => {
    if (!po) return;
    setApproving(true);
    try {
      const res = await authFetch(`/api/procurement/purchase-orders/${po.id}/status`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'approved' }),
      });
      if (res.ok) { show(`${po.po_number} approved — the order is on its way to the supplier.`, { variant: 'success' }); load(); }
      else { const e = await res.json().catch(() => ({})); show(e.detail || 'Could not approve this order', { variant: 'error' }); }
    } finally { setApproving(false); }
  };

  if (notFound) return <div className="p-8 text-ink-muted">Purchase order not found.</div>;
  if (!po) return <div className="p-8 animate-pulse text-ink-muted">Loading purchase order…</div>;

  return (
    <main className="min-h-screen bg-surface p-6 md:p-10 text-ink">
      {/* Toolbar — hidden when printing. Approve is primary; Print is secondary. */}
      <div className="max-w-3xl mx-auto flex items-center justify-between gap-3 mb-4 print:hidden">
        <button onClick={() => router.back()} className="inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink">
          <ArrowLeft className="w-4 h-4" /> Back
        </button>
        <div className="flex items-center gap-2">
          <button onClick={() => window.print()} className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-surface border border-line text-ink text-sm font-medium hover:bg-surface-2">
            <Printer className="w-4 h-4" /> Print / PDF
          </button>
          {canApprove ? (
            <button onClick={approve} disabled={approving}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl sunset-gradient text-white text-sm font-semibold shadow-sunset disabled:opacity-60">
              <Check className="w-4 h-4" /> {approving ? 'Approving…' : 'Approve order'}
            </button>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-emerald-50 text-emerald-700 text-sm font-medium ring-1 ring-emerald-200">
              <CheckCircle2 className="w-4 h-4" /> {po.status.replace('_', ' ')}
            </span>
          )}
        </div>
      </div>

      {/* "You came for this item" banner — keeps the acted-on item front of mind. */}
      {focusItem && (
        <div className="max-w-3xl mx-auto mb-4 print:hidden rounded-xl bg-teal-50 ring-1 ring-teal-100 px-4 py-2.5 text-sm text-teal-900">
          You&apos;re here to reorder <strong>{focusItem}</strong> — it&apos;s highlighted below.
          {canApprove ? ' Approve this order to send it.' : ''}
        </div>
      )}

      {/* Document */}
      <div className="max-w-3xl mx-auto border border-line rounded-xl p-8 print:border-0 print:p-0">
        <div className="flex items-start justify-between border-b border-line pb-5 mb-5">
          <div>
            <h1 className="text-2xl font-bold">Purchase Order</h1>
            <p className="text-ink-muted mt-1">{po.po_number}</p>
          </div>
          <div className="text-end">
            <p className="text-lg font-bold gradient-text">{PRODUCT_NAME}</p>
            <p className="text-xs text-ink-muted">Procurement</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-6 mb-6 text-sm">
          <div><p className="text-ink-muted">Supplier</p><p className="font-medium">{po.supplier_name}</p></div>
          <div className="text-end"><p className="text-ink-muted">Status</p><p className="font-medium capitalize">{po.status.replace('_', ' ')}</p></div>
          <div><p className="text-ink-muted">Created</p><p className="font-medium">{fmtDate(po.created_at)}</p></div>
          <div className="text-end"><p className="text-ink-muted">Approved</p><p className="font-medium">{fmtDate(po.approved_at)}</p></div>
        </div>

        <table className="w-full text-sm mb-6">
          <thead>
            <tr className="text-start border-b-2 border-line">
              <th className="py-2 font-semibold">Item</th>
              <th className="py-2 font-semibold text-end">Qty</th>
              <th className="py-2 font-semibold text-end">Unit cost</th>
              <th className="py-2 font-semibold text-end">Line total</th>
            </tr>
          </thead>
          <tbody>
            {po.lines.map((l) => {
              const match = isMatch(l.item_name);
              return (
                <tr key={l.id} ref={match ? rowRef : undefined}
                  className={`border-b border-line/60 ${match ? 'bg-teal-50/70 ring-1 ring-teal-200' : ''}`}>
                  <td className="py-2 ps-1">
                    {match && <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500 me-2 align-middle" />}
                    <span className={match ? 'font-semibold text-teal-900' : ''}>{l.item_name}</span>
                  </td>
                  <td className="py-2 text-end">{l.quantity.toLocaleString()}</td>
                  <td className="py-2 text-end">{money(l.unit_cost)}</td>
                  <td className="py-2 text-end">{money(l.line_total)}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-line">
              <td colSpan={3} className="py-3 text-end font-semibold">Total</td>
              <td className="py-3 text-end font-bold text-base">{money(po.total_amount)}</td>
            </tr>
          </tfoot>
        </table>

        {po.receipts.length > 0 && (
          <div className="text-xs text-ink-muted mb-6">
            Goods receipts: {po.receipts.map((r) => `${r.receipt_number} (${r.status})`).join(', ')}
          </div>
        )}

        <div className="border-t border-line pt-4 text-xs text-ink-muted">
          {po.source === 'forecast_reorder' && (
            <p className="inline-flex items-center gap-1.5">
              <TrendingUp className="h-3.5 w-3.5 text-teal-600" aria-hidden />
              Auto-generated from demand forecast.
            </p>
          )}
          <p className="mt-1">This document is a system-of-record purchase order. Synthetic demo data.</p>
        </div>
      </div>

      {/* Repeat the primary action at the bottom so a long PO never hides it. */}
      {canApprove && (
        <div className="max-w-3xl mx-auto mt-5 print:hidden flex justify-end">
          <button onClick={approve} disabled={approving}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl sunset-gradient text-white text-sm font-semibold shadow-sunset disabled:opacity-60">
            <Check className="w-4 h-4" /> {approving ? 'Approving…' : `Approve order — ${money(po.total_amount)}`}
          </button>
        </div>
      )}

      <div className="max-w-3xl mx-auto mt-6 print:hidden">
        <AuditTimeline entityId={po.id} limit={20} />
      </div>
    </main>
  );
}
