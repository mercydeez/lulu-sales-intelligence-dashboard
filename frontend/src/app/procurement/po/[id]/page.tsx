'use client';

/**
 * Printable Purchase Order document (Part III-H). A clean, print-optimised view
 * of a PO that a buyer can send to a supplier or save as PDF (browser print →
 * Save as PDF). Dependency-free: no server-side PDF library.
 */
import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Printer, ArrowLeft } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import AuditTimeline from '@/components/AuditTimeline';

interface POLine { id: number; item_name: string; quantity: number; unit_cost: number; line_total: number; received_qty: number; }
interface PODetail {
  id: number; po_number: string; status: string; supplier_name: string;
  total_amount: number; currency: string; source: string;
  created_at: string | null; approved_at: string | null;
  lines: POLine[]; receipts: { receipt_number: string; status: string }[];
}

export default function PrintablePOPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { authFetch } = useAuth();
  const [po, setPo] = useState<PODetail | null>(null);
  const [notFound, setNotFound] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`/api/procurement/purchase-orders/${id}`);
      if (res.ok) setPo(await res.json()); else setNotFound(true);
    } catch { setNotFound(true); }
  }, [authFetch, id]);
  useEffect(() => { load(); }, [load]);

  const money = (n: number) => `${po?.currency ?? 'AED'} ${new Intl.NumberFormat('en-AE', { minimumFractionDigits: 2 }).format(n)}`;
  const fmtDate = (s: string | null) => (s ? new Date(s).toLocaleDateString('en-AE', { year: 'numeric', month: 'short', day: 'numeric' }) : '—');

  if (notFound) return <div className="p-8 text-ink-muted">Purchase order not found.</div>;
  if (!po) return <div className="p-8 animate-pulse text-ink-muted">Loading purchase order…</div>;

  return (
    <main className="min-h-screen bg-white p-6 md:p-10 text-ink">
      {/* Toolbar — hidden when printing */}
      <div className="max-w-3xl mx-auto flex items-center justify-between mb-6 print:hidden">
        <button onClick={() => router.push('/procurement')} className="inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink">
          <ArrowLeft className="w-4 h-4" /> Back to procurement
        </button>
        <button onClick={() => window.print()} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl sunset-gradient text-white text-sm font-semibold shadow-sunset">
          <Printer className="w-4 h-4" /> Print / Save as PDF
        </button>
      </div>

      {/* Document */}
      <div className="max-w-3xl mx-auto border border-line rounded-xl p-8 print:border-0 print:p-0">
        <div className="flex items-start justify-between border-b border-line pb-5 mb-5">
          <div>
            <h1 className="text-2xl font-bold">Purchase Order</h1>
            <p className="text-ink-muted mt-1">{po.po_number}</p>
          </div>
          <div className="text-right">
            <p className="text-lg font-bold gradient-text">Lulu Intelligence</p>
            <p className="text-xs text-ink-muted">Procurement</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-6 mb-6 text-sm">
          <div>
            <p className="text-ink-muted">Supplier</p>
            <p className="font-medium">{po.supplier_name}</p>
          </div>
          <div className="text-right">
            <p className="text-ink-muted">Status</p>
            <p className="font-medium capitalize">{po.status.replace('_', ' ')}</p>
          </div>
          <div>
            <p className="text-ink-muted">Created</p>
            <p className="font-medium">{fmtDate(po.created_at)}</p>
          </div>
          <div className="text-right">
            <p className="text-ink-muted">Approved</p>
            <p className="font-medium">{fmtDate(po.approved_at)}</p>
          </div>
        </div>

        <table className="w-full text-sm mb-6">
          <thead>
            <tr className="text-left border-b-2 border-line">
              <th className="py-2 font-semibold">Item</th>
              <th className="py-2 font-semibold text-end">Qty</th>
              <th className="py-2 font-semibold text-end">Unit cost</th>
              <th className="py-2 font-semibold text-end">Line total</th>
            </tr>
          </thead>
          <tbody>
            {po.lines.map((l) => (
              <tr key={l.id} className="border-b border-line/60">
                <td className="py-2">{l.item_name}</td>
                <td className="py-2 text-end">{l.quantity.toLocaleString()}</td>
                <td className="py-2 text-end">{money(l.unit_cost)}</td>
                <td className="py-2 text-end">{money(l.line_total)}</td>
              </tr>
            ))}
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
          {po.source === 'forecast_reorder' && <p>📈 Auto-generated from demand forecast.</p>}
          <p className="mt-1">This document is a system-of-record purchase order. Synthetic demo data.</p>
        </div>
      </div>

      {/* Per-PO audit trail — on-screen only, hidden when printing */}
      <div className="max-w-3xl mx-auto mt-6 print:hidden">
        <AuditTimeline entityId={po.id} limit={20} />
      </div>
    </main>
  );
}
