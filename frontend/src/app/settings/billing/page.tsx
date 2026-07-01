'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import {
  PageHeader, Card, Badge, Button, Modal, EmptyState, SkeletonCard, ErrorState,
  Stagger, RevealItem,
} from '@/components/ui';
import type { BadgeVariant } from '@/components/ui';
import { apiGet, apiPost, authFetch, ApiError } from '@/lib/apiClient';
import { CreditCard, FileText, ShieldAlert, Printer } from 'lucide-react';

const AED = (n: number | null | undefined) =>
  n == null ? '—' : `AED ${n.toLocaleString('en-AE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const STATUS_TONE: Record<string, BadgeVariant> = {
  draft: 'neutral', issued: 'amber', paid: 'success', void: 'neutral', credited: 'violet',
};

interface Subscription { exists: boolean; plan: string; status?: string; billing_provider?: string;
  currency?: string; monthly_price_aed?: number | null; custom_pricing?: boolean; current_period_end?: string | null; }
interface InvoiceRow { id: number; invoice_number: string; status: string; total_aed: number | null;
  vat_amount_aed: number | null; subtotal_aed: number | null; created_at: string | null; due_at: string | null; }
interface InvoiceDetail extends InvoiceRow {
  supplier_legal_name?: string; supplier_trn?: string; customer_legal_name?: string; customer_trn?: string;
  vat_rate?: number; payment_terms?: string; payment_instructions?: string; po_number?: string;
  e_invoice_status?: string; e_invoice_provider?: string; e_invoice_external_id?: string;
  lines: { description: string; quantity: number; unit_price_aed: number; line_subtotal_aed: number;
    vat_amount_aed: number; line_total_aed: number }[];
  note?: string;
}

const EINV_TONE: Record<string, BadgeVariant> = {
  not_submitted: 'neutral', submitted: 'amber', accepted: 'success', rejected: 'danger',
};

export default function BillingPage() {
  const { user } = useAuth();
  const { t } = useLanguage();
  const isAdmin = ['super_admin', 'admin'].includes(user?.role ?? '');

  const [sub, setSub] = useState<Subscription | null>(null);
  const [invoices, setInvoices] = useState<InvoiceRow[]>([]);
  const [detail, setDetail] = useState<InvoiceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [s, inv] = await Promise.all([
        apiGet<Subscription>('/api/billing/subscription'),
        apiGet<{ invoices: InvoiceRow[] }>('/api/billing/invoices'),
      ]);
      setSub(s); setInvoices(inv.invoices ?? []);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load billing');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { if (isAdmin) load(); else setLoading(false); }, [isAdmin, load]);

  const openInvoice = async (id: number) => {
    try { setDetail(await apiGet<InvoiceDetail>(`/api/billing/invoices/${id}`)); } catch { /* ignore */ }
  };

  const [einvBusy, setEinvBusy] = useState(false);
  const submitEInvoice = async () => {
    if (!detail) return;
    setEinvBusy(true);
    try {
      await apiPost(`/api/billing/invoices/${detail.id}/einvoice/submit`, { provider: 'mock' });
      setDetail(await apiGet<InvoiceDetail>(`/api/billing/invoices/${detail.id}`));
    } catch { /* surfaced via reloaded status */ }
    finally { setEinvBusy(false); }
  };
  const isSuper = user?.role === 'super_admin';

  const printInvoice = async (id: number) => {
    const res = await authFetch(`/api/billing/invoices/${id}/print`);
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const w = window.open(url, '_blank');
    if (!w) { const a = document.createElement('a'); a.href = url; a.download = `invoice-${id}.html`; a.click(); }
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  };

  if (!isAdmin) {
    return (
      <main className="min-h-screen p-4 md:p-8"><div className="max-w-3xl mx-auto">
        <Card padding="lg" className="text-center">
          <ShieldAlert className="w-8 h-8 text-amber-500 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-ink">Admin access required</h2>
          <p className="text-sm text-ink-muted mt-1">Only a tenant administrator can view billing.</p>
        </Card>
      </div></main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        <PageHeader title={t('billing.title')} description={t('billing.description')} icon={<CreditCard className="w-5 h-5" />} />

        {loading ? <div className="space-y-4"><SkeletonCard /><SkeletonCard /></div>
        : error ? <ErrorState title="Couldn't load billing" description={error} onRetry={load} />
        : (
          <Stagger className="space-y-6">
            {/* Subscription */}
            {sub && (
              <RevealItem><Card padding="lg">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Subscription</h3>
                  <Badge variant="teal">{sub.plan.charAt(0).toUpperCase() + sub.plan.slice(1)} plan</Badge>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                  <div><p className="text-xs text-ink-muted">Status</p><p className="font-medium text-ink">{sub.status ?? 'manual'}</p></div>
                  <div><p className="text-xs text-ink-muted">Provider</p><p className="font-medium text-ink">{sub.billing_provider ?? 'manual'}</p></div>
                  <div><p className="text-xs text-ink-muted">Monthly</p><p className="font-medium text-ink">{sub.custom_pricing ? 'Custom' : AED(sub.monthly_price_aed)}</p></div>
                  <div><p className="text-xs text-ink-muted">Currency</p><p className="font-medium text-ink">{sub.currency ?? 'AED'}</p></div>
                </div>
                {sub.custom_pricing && (
                  <p className="text-xs text-ink-muted mt-3">Enterprise / manual invoicing — contact sales for a quote and purchase order.</p>
                )}
              </Card></RevealItem>
            )}

            {/* Invoices */}
            <RevealItem><Card padding="lg">
              <div className="flex items-center gap-2 mb-4">
                <FileText className="w-4 h-4 text-teal-600" />
                <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Invoices</h3>
              </div>
              {invoices.length === 0 ? (
                <EmptyState title="No invoices yet" description="Invoices appear here once your account is billed." />
              ) : (
                <div className="space-y-2">
                  {invoices.map((inv) => (
                    <button key={inv.id} onClick={() => openInvoice(inv.id)}
                      className="w-full flex items-center justify-between gap-3 rounded-xl border border-line p-3 hover:bg-surface-2/60 text-start transition-all">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-ink truncate">{inv.invoice_number}</p>
                        <p className="text-xs text-ink-muted">{inv.created_at ? new Date(inv.created_at).toLocaleDateString() : ''}</p>
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <span className="text-sm font-semibold text-ink">{AED(inv.total_aed)}</span>
                        <Badge variant={STATUS_TONE[inv.status] ?? 'neutral'}>{inv.status}</Badge>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </Card></RevealItem>

            <p className="text-xs text-ink-muted">
              Draft — VAT/invoice content requires review by a qualified UAE legal/tax professional before production use.
            </p>
          </Stagger>
        )}

        {/* Invoice detail */}
        <Modal open={!!detail} onClose={() => setDetail(null)} title={detail?.invoice_number ?? 'Invoice'}>
          {detail && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div><p className="text-xs text-ink-muted">From</p><p className="text-ink">{detail.supplier_legal_name ?? '—'}</p>
                  {detail.supplier_trn && <p className="text-xs text-ink-muted">TRN {detail.supplier_trn}</p>}</div>
                <div><p className="text-xs text-ink-muted">Bill to</p><p className="text-ink">{detail.customer_legal_name ?? '—'}</p>
                  {detail.customer_trn && <p className="text-xs text-ink-muted">TRN {detail.customer_trn}</p>}</div>
              </div>
              <div className="border border-line rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-surface-2/60 text-ink-muted text-xs">
                    <tr><th className="text-start p-2">Description</th><th className="text-end p-2">Qty</th>
                      <th className="text-end p-2">Unit</th><th className="text-end p-2">VAT</th><th className="text-end p-2">Total</th></tr>
                  </thead>
                  <tbody>
                    {detail.lines.map((l, i) => (
                      <tr key={i} className="border-t border-line/60">
                        <td className="p-2 text-ink">{l.description}</td>
                        <td className="p-2 text-end">{l.quantity}</td>
                        <td className="p-2 text-end">{AED(l.unit_price_aed)}</td>
                        <td className="p-2 text-end">{AED(l.vat_amount_aed)}</td>
                        <td className="p-2 text-end font-medium">{AED(l.line_total_aed)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-col items-end gap-1">
                <span className="text-ink-soft">Subtotal: {AED(detail.subtotal_aed)}</span>
                <span className="text-ink-soft">VAT ({((detail.vat_rate ?? 0.05) * 100).toFixed(0)}%): {AED(detail.vat_amount_aed)}</span>
                <span className="text-base font-semibold text-ink">Total: {AED(detail.total_aed)}</span>
              </div>
              <div className="flex justify-end">
                <Button variant="secondary" size="sm" onClick={() => printInvoice(detail.id)}>
                  <Printer className="w-4 h-4 me-1.5" /> Print / PDF
                </Button>
              </div>
              {/* E-invoicing status (UAE) */}
              <div className="flex items-center justify-between rounded-xl bg-surface-2/60 p-3">
                <div>
                  <p className="text-xs text-ink-muted mb-1">E-invoicing</p>
                  <div className="flex items-center gap-2">
                    <Badge variant={EINV_TONE[detail.e_invoice_status ?? 'not_submitted'] ?? 'neutral'}>
                      {(detail.e_invoice_status ?? 'not_submitted').replace('_', ' ')}
                    </Badge>
                    {detail.e_invoice_external_id && (
                      <span className="text-xs text-ink-muted">{detail.e_invoice_external_id}</span>
                    )}
                  </div>
                </div>
                {isSuper && detail.status === 'issued' && detail.e_invoice_status !== 'accepted' && (
                  <Button variant="secondary" size="sm" onClick={submitEInvoice} disabled={einvBusy}>
                    {einvBusy ? 'Submitting…' : 'Submit e-invoice'}
                  </Button>
                )}
              </div>

              {detail.payment_instructions && (
                <div className="rounded-xl bg-surface-2/60 p-3">
                  <p className="text-xs text-ink-muted mb-1">Payment instructions</p>
                  <p className="text-ink whitespace-pre-wrap">{detail.payment_instructions}</p>
                </div>
              )}
              {detail.note && <p className="text-xs text-ink-muted">{detail.note}</p>}
            </div>
          )}
        </Modal>
      </div>
    </main>
  );
}
