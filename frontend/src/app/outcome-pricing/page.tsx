'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import {
  PageHeader, Card, Badge, Button, Input, EmptyState, SkeletonCard, useToast, Stagger, RevealItem,
  NoPermissionState,
} from '@/components/ui';
import { apiGet, apiPut, apiPost, ApiError } from '@/lib/apiClient';
import { Scale, ShieldCheck, FileText } from 'lucide-react';

const AED = (n: number | null | undefined) =>
  n == null ? '—' : `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: 0 })}`;

interface Plan { base_fee_aed: number; value_share_pct: number; savings_guarantee_multiple: number; active: boolean; }
interface Statement { confirmed_value_aed: number; base_fee_aed: number; value_share_pct: number;
  variable_fee_aed: number; total_fee_aed: number; confirmed_count: number; plan_active: boolean;
  value_to_fee_ratio: number | null;
  guarantee: { multiple: number; required_savings_aed: number; met: boolean; variable_waived: boolean }; }
interface Valuation { basis: string; daily_revenue_aed: number | null; window_revenue_aed: number | null;
  suggested_value_aed: number | null; method: string | null; }
interface Realization { id: number; finding_id: number; title: string; entity_type: string; entity_name: string | null;
  confirmed_value_aed: number | null; status: string; metric_before: number | null; metric_after: number | null;
  valuation?: Valuation; }

export default function OutcomePricingPage() {
  const { user } = useAuth();
  const { show } = useToast();
  const isAdmin = ['super_admin', 'admin'].includes(user?.role ?? '');
  const isSuper = user?.role === 'super_admin';

  const [plan, setPlan] = useState<Plan | null>(null);
  const [statement, setStatement] = useState<Statement | null>(null);
  const [realizations, setRealizations] = useState<Realization[]>([]);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, s, r] = await Promise.all([
        apiGet<Plan>('/api/outcome-pricing/plan'),
        apiGet<Statement>('/api/outcome-pricing/statement'),
        apiGet<{ realizations: Realization[] }>('/api/outcome-pricing/realizations'),
      ]);
      setPlan(p); setStatement(s);
      const rl = r.realizations ?? [];
      setRealizations(rl);
      // Pre-fill the input with the platform's conservative suggestion (operator confirms/edits).
      setDrafts((d) => {
        const next = { ...d };
        rl.forEach((x) => {
          if (x.status === 'pending' && next[x.id] == null && x.valuation?.suggested_value_aed != null) {
            next[x.id] = String(x.valuation.suggested_value_aed);
          }
        });
        return next;
      });
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);
  useEffect(() => { if (isAdmin) load(); else setLoading(false); }, [isAdmin, load]);

  const savePlan = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      await apiPut('/api/outcome-pricing/plan', plan);
      show('Plan saved', { variant: 'success' });
      await load();
    } catch (e) { show(e instanceof ApiError ? e.message : 'Save failed', { variant: 'error' }); }
    finally { setBusy(false); }
  };

  const confirm = async (id: number) => {
    const val = Number(drafts[id]);
    if (!Number.isFinite(val) || val < 0) { show('Enter a valid AED value', { variant: 'error' }); return; }
    setBusy(true);
    try {
      await apiPost(`/api/outcome-pricing/realizations/${id}`, { confirmed_value_aed: val, status: 'confirmed' });
      await load();
    } catch (e) { show(e instanceof ApiError ? e.message : 'Failed', { variant: 'error' }); }
    finally { setBusy(false); }
  };

  const dismiss = async (id: number) => {
    setBusy(true);
    try { await apiPost(`/api/outcome-pricing/realizations/${id}`, { status: 'dismissed' }); await load(); }
    catch { /* ignore */ } finally { setBusy(false); }
  };

  const generateInvoice = async () => {
    setBusy(true);
    try {
      const res = await apiPost<{ invoice_number: string }>('/api/outcome-pricing/invoice', {});
      show(`Draft invoice ${res.invoice_number} created — see Billing`, { variant: 'success' });
    } catch (e) { show(e instanceof ApiError ? e.message : 'Could not create invoice', { variant: 'error' }); }
    finally { setBusy(false); }
  };

  if (!isAdmin) {
    return (
      <main className="min-h-screen p-4 md:p-8"><div className="max-w-3xl mx-auto">
        <Card padding="none">
          <NoPermissionState
            title="Admin access required"
            description="Outcome pricing is limited to tenant administrators."
          />
        </Card>
      </div></main>
    );
  }

  const pending = realizations.filter((r) => r.status === 'pending');

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        <PageHeader
          title="Outcome pricing"
          description="Pay on proven outcomes. We bill a share of the savings you confirm — and waive it if we don't clear the guarantee."
          icon={<Scale className="w-5 h-5" />}
        />

        {loading ? <div className="space-y-4"><SkeletonCard /><SkeletonCard /></div> : (
          <Stagger className="space-y-6">
            {/* Statement */}
            {statement && (
              <RevealItem><Card padding="lg" className="bg-teal-50/40">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">This statement</h3>
                  {statement.guarantee.variable_waived
                    ? <Badge variant="amber">guarantee not met — variable waived</Badge>
                    : <Badge variant="success">guarantee met</Badge>}
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                  <Stat label={`Confirmed value (${statement.confirmed_count})`} value={AED(statement.confirmed_value_aed)} big />
                  <Stat label="Base fee" value={AED(statement.base_fee_aed)} />
                  <Stat label={`Value share (${statement.value_share_pct}%)`} value={AED(statement.variable_fee_aed)} />
                  <Stat label="Total fee" value={AED(statement.total_fee_aed)} big />
                </div>
                <p className="text-xs text-ink-muted mt-3">
                  {statement.value_to_fee_ratio != null
                    ? `The platform returned ${statement.value_to_fee_ratio}× its fee in confirmed value. `
                    : ''}
                  Guarantee: save ≥ {statement.guarantee.multiple}× base ({AED(statement.guarantee.required_savings_aed)}) or the value-share is waived.
                </p>
                {isSuper && statement.total_fee_aed > 0 && (
                  <div className="mt-4">
                    <Button onClick={generateInvoice} disabled={busy}>
                      <FileText className="w-4 h-4 me-1.5" /> Generate draft invoice
                    </Button>
                  </div>
                )}
              </Card></RevealItem>
            )}

            {/* Plan config */}
            {plan && (
              <RevealItem><Card padding="lg">
                <div className="flex items-center gap-2 mb-4">
                  <ShieldCheck className="w-4 h-4 text-teal-600" />
                  <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Pricing plan</h3>
                  {plan.active && <Badge variant="success">active</Badge>}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <Input label="Base fee (AED/period)" type="number" value={String(plan.base_fee_aed)}
                    onChange={(e) => setPlan({ ...plan, base_fee_aed: Number(e.target.value) })} />
                  <Input label="Value share (%)" type="number" value={String(plan.value_share_pct)}
                    onChange={(e) => setPlan({ ...plan, value_share_pct: Number(e.target.value) })} />
                  <Input label="Savings guarantee (× base)" type="number" value={String(plan.savings_guarantee_multiple)}
                    onChange={(e) => setPlan({ ...plan, savings_guarantee_multiple: Number(e.target.value) })} />
                </div>
                <label className="flex items-center gap-2 mt-4 text-sm text-ink-soft cursor-pointer">
                  <input type="checkbox" checked={plan.active} onChange={(e) => setPlan({ ...plan, active: e.target.checked })} />
                  Plan active
                </label>
                <div className="mt-4"><Button onClick={savePlan} disabled={busy} size="sm">Save plan</Button></div>
              </Card></RevealItem>
            )}

            {/* Realizations to confirm */}
            <RevealItem><Card padding="lg">
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-1">Confirm realised value</h3>
              <p className="text-xs text-ink-muted mb-4">
                Each row is a recommendation the measure loop verified as improved. Enter the AED value you agree it
                delivered — only confirmed value is ever billed. We never estimate this for you.
              </p>
              {pending.length === 0 ? <EmptyState title="Nothing to confirm" description="Improved findings will appear here for valuation." />
              : (
                <div className="space-y-3">
                  {pending.map((r) => (
                    <div key={r.id} className="rounded-xl border border-line p-3">
                      <p className="text-sm font-medium text-ink">{r.title}</p>
                      <p className="text-xs text-ink-muted mb-1">
                        {r.entity_type}{r.entity_name ? `: ${r.entity_name}` : ''}
                        {r.metric_before != null && r.metric_after != null ? ` · metric ${r.metric_before} → ${r.metric_after}` : ''}
                      </p>
                      {r.valuation?.suggested_value_aed != null && (
                        <p className="text-xs text-teal-700 mb-2">
                          Suggested {AED(r.valuation.suggested_value_aed)} · {r.valuation.method}
                          {r.valuation.daily_revenue_aed != null ? ` (${r.valuation.basis} ≈ ${AED(r.valuation.daily_revenue_aed)}/day)` : ''}
                        </p>
                      )}
                      <div className="flex items-center gap-2 flex-wrap">
                        <Input type="number" placeholder="AED value realised" className="w-48"
                          value={drafts[r.id] ?? ''} onChange={(e) => setDrafts((d) => ({ ...d, [r.id]: e.target.value }))} />
                        <Button size="sm" onClick={() => confirm(r.id)} disabled={busy}>Confirm</Button>
                        <Button size="sm" variant="secondary" onClick={() => dismiss(r.id)} disabled={busy}>Dismiss</Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card></RevealItem>

            <p className="text-xs text-ink-muted">
              Draft — outcome pricing terms and VAT treatment require review by a qualified UAE legal/tax professional.
            </p>
          </Stagger>
        )}
      </div>
    </main>
  );
}

function Stat({ label, value, big }: { label: string; value: string; big?: boolean }) {
  return (
    <div>
      <p className="text-xs text-ink-muted">{label}</p>
      <p className={`${big ? 'text-xl' : 'text-base'} font-semibold text-ink mt-0.5`}>{value}</p>
    </div>
  );
}
