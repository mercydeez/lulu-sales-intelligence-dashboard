'use client';

/**
 * Retention & Commercial Orchestration — the closed-loop campaign journey on
 * one page: draft -> audience -> simulate -> approve -> activate -> live
 * offers (evaluate / idempotent redeem) -> treatment-vs-control outcomes.
 * All customer data is SYNTHETIC and labelled as such.
 */
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import {
  PageHeader, Card, Badge, Button, Input, Select, EmptyState, SkeletonCard,
  ErrorState, NoPermissionState, useToast,
  Table, TableHead, TableBody, TableRow, Th, Td,
} from '@/components/ui';
import type { BadgeVariant } from '@/components/ui';
import { apiGet, apiPost, ApiError } from '@/lib/apiClient';
import { fetchStores, fetchItems } from '@/lib/api';
import type { Store, Item } from '@/types';
import { Users, RefreshCw, Plus } from 'lucide-react';

const STATUS_TONE: Record<string, BadgeVariant> = {
  draft: 'neutral', audience_ready: 'teal', simulated: 'violet',
  pending_approval: 'amber', approved: 'success', active: 'success',
  paused: 'danger', completed: 'neutral', measured: 'teal', cancelled: 'neutral',
};

interface Campaign {
  id: number; name: string; status: string; store_name: string; item_name: string;
  store_id: number; item_id: number; starts_on: string; ends_on: string;
  discount_budget_aed: string; budget_reserved_aed: string; budget_spent_aed: string;
  max_discount_pct: string; min_margin_pct: string; control_pct: string;
  paused_reason: string | null; audience_size: number;
  simulation: Simulation | null;
}
interface Simulation {
  audience: number; control: number; treated_offers: number; reminders: number;
  suppressed: number; expected_redemptions: number;
  expected_discount_spend_aed: string; expected_incremental_value_aed: string;
  budget_sufficient: boolean; atp_units: number; shortfall_units: number;
  substitute: { name: string } | null;
  transfer_recommendation: { from_store: string; units: number } | null;
  procurement_requisition: Record<string, unknown> | null;
}
interface Offer {
  id: number; customer_ref: string; archetype: string; cohort: string;
  churn_score: string; response_prob: string; action: string; discount_pct: string;
  expected_value_aed: string; reason_codes: string[]; status: string;
  item_name: string | null;
}
interface Outcomes {
  treatment: { n: number; purchase_rate: number; redemptions: number; discount_spend_aed: string };
  control: { n: number; purchase_rate: number };
  incremental_purchase_rate: number;
  budget: { approved_aed: string; spent_aed: string; reserved_aed: string };
  caveats: string[];
}

interface Conflict { code: string; department: string; evidence: string; impact: string;
  resolution: string; required_approver: string; blocks_campaign: boolean; }
interface ScenarioRow {
  label: string; discount_pct: string; demand_low: number; demand_expected: number;
  demand_high: number; baseline_units: number; policy_ok: boolean; policy_reason: string | null;
  expected_redemptions: number; response_prob: number;
  category: { net_incremental_category_units: number; cannibalized_units: number;
    halo_units: number; forward_bought_units: number };
  inventory: { available_to_promise: number; stockout_risk_high_case: boolean;
    expected_leftover_units: number; expected_expiry_units: number;
    expected_expiry_loss_aed: string | null };
  finance: { net_profit_low_aed: string; net_profit_expected_aed: string;
    net_profit_high_aed: string; worst_credible_loss_aed: string;
    discount_liability_aed: string; weekly_discount_cash_aed: string };
  risk_adjusted: { risk_adjusted_value_aed: string; downside_penalty_aed: string;
    cash_strain_penalty_aed: string };
  monte_carlo?: { trials: number; profit_p10_aed: string; profit_p50_aed: string;
    profit_p90_aed: string; profit_mean_aed: string; cvar_5pct_aed: string;
    loss_probability: number; stockout_probability: number;
    units_sold_p10: number; units_sold_p50: number; units_sold_p90: number;
    expected_leftover_units: number; expected_expiry_loss_aed: string };
  cash_at_risk?: { cash_at_risk_aed: string; committed_cash_aed: string };
  procurement_options: { option: string; units: number; cost_aed: string;
    in_time?: boolean; requires_approval?: boolean; note?: string }[];
  conflicts: Conflict[];
}
interface ScenarioPack {
  objective: string;
  data_readiness: { status: string; blockers: string[]; warnings: string[] };
  baseline_no_campaign: { units_over_horizon: number; daily_avg: number; source: string;
    p10?: number; p50?: number; p90?: number;
    quantiles?: { observations: number; zero_share: number; intermittent: boolean;
      status: string; method: string } | null };
  audience: { audience_size: number; treatment: number; control: number;
    avg_churn: number; consent_share: number };
  scenarios: ScenarioRow[];
  recommendation: { decision: string; chosen: string | null; reason_codes: string[];
    conditions: string[] };
  department_views: Record<string, { headline: string; metrics: Record<string, unknown>;
    reason_codes: string[] }>;
  confidence: string; synthetic_data: boolean; assumptions: string[];
}

const DECISION_TONE: Record<string, BadgeVariant> = {
  APPROVE: 'success', APPROVE_WITH_CONDITIONS: 'teal', PILOT: 'amber',
  REJECT: 'danger', NEEDS_MORE_DATA: 'neutral',
};
const OBJECTIVES = [
  ['churn_retention', 'Churn retention'], ['lapsed_reactivation', 'Lapsed reactivation'],
  ['excess_stock_clearance', 'Excess-stock clearance'], ['near_expiry_waste', 'Near-expiry waste reduction'],
  ['basket_growth', 'Basket growth'], ['new_product_trial', 'New-product trial'],
  ['category_growth', 'Category growth'], ['seasonal_event', 'Seasonal event'],
];
const DEPT_ORDER = ['marketing', 'cmo', 'category', 'inventory', 'operations',
  'procurement', 'finance', 'cto_data', 'compliance'];

export default function RetentionPage() {
  const { user } = useAuth();
  const { show } = useToast();
  const isMarketing = ['super_admin', 'admin'].includes(user?.role ?? '')
    || !!user?.permissions?.can_manage_promotions;
  const isApprover = ['super_admin', 'regional_manager'].includes(user?.role ?? '');

  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [outcomes, setOutcomes] = useState<Outcomes | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [stores, setStores] = useState<Store[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [pack, setPack] = useState<ScenarioPack | null>(null);
  const [form, setForm] = useState({
    name: '', objective: 'churn_retention', store_id: '', item_id: '', starts_on: '', ends_on: '',
    discount_budget_aed: '500', max_discount_pct: '15', min_margin_pct: '10',
    control_pct: '10', churn_threshold: '0.5', safety_stock_units: '20',
  });

  const load = useCallback(async (keepSelection = false) => {
    setError(null);
    try {
      const res = await apiGet<{ campaigns: Campaign[] }>('/api/retention/campaigns');
      setCampaigns(res.campaigns ?? []);
      if (keepSelection && selected) {
        const again = res.campaigns.find(c => c.id === selected.id);
        if (again) await openCampaign(again.id);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load campaigns');
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id]);

  useEffect(() => {
    if (!isMarketing) { setLoading(false); return; }
    load();
    fetchStores().then(setStores).catch(() => {});
    fetchItems().then(setItems).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMarketing]);

  const openCampaign = async (id: number) => {
    try {
      const camp = await apiGet<Campaign>(`/api/retention/campaigns/${id}`);
      setSelected(camp);
      setOutcomes(null);
      // The decision pack is persisted under simulation.scenario_pack.
      const sim = camp.simulation as (Simulation & { scenario_pack?: ScenarioPack }) | null;
      setPack(sim?.scenario_pack ?? null);
      if (!['draft'].includes(camp.status)) {
        const o = await apiGet<{ offers: Offer[] }>(`/api/retention/campaigns/${id}/offers`);
        setOffers(o.offers ?? []);
      } else { setOffers([]); }
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Failed to open campaign', { variant: 'error' });
    }
  };

  const runScenario = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const p = await apiPost<ScenarioPack>(`/api/retention/campaigns/${selected.id}/scenario`, {});
      setPack(p);
      show(`Decision pack ready — recommendation: ${p.recommendation.decision}`, { variant: 'success' });
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Could not build the scenario pack', { variant: 'error' });
    } finally { setBusy(false); }
  };

  const act = async (path: string, body: Record<string, unknown> = {}, success?: string) => {
    if (!selected) return;
    setBusy(true);
    try {
      await apiPost(`/api/retention/campaigns/${selected.id}/${path}`, body);
      if (success) show(success, { variant: 'success' });
      await load();
      await openCampaign(selected.id);
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Action failed', { variant: 'error' });
    } finally { setBusy(false); }
  };

  const create = async () => {
    setBusy(true);
    try {
      const body = {
        name: form.name, objective: form.objective,
        store_id: Number(form.store_id), item_id: Number(form.item_id),
        starts_on: form.starts_on, ends_on: form.ends_on,
        discount_budget_aed: form.discount_budget_aed,
        max_discount_pct: form.max_discount_pct, min_margin_pct: form.min_margin_pct,
        control_pct: form.control_pct, churn_threshold: Number(form.churn_threshold),
        safety_stock_units: Number(form.safety_stock_units),
      };
      const res = await apiPost<{ id: number }>('/api/retention/campaigns', body);
      show('Campaign drafted', { variant: 'success' });
      setShowCreate(false);
      await load();
      await openCampaign(res.id);
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Could not create the campaign', { variant: 'error' });
    } finally { setBusy(false); }
  };

  const redeemOffer = async (offerId: number) => {
    if (!selected) return;
    setBusy(true);
    try {
      // Stable key per offer: clicking twice demonstrates idempotent replay.
      const res = await apiPost<{ replay: boolean; amount_aed: string; auto_paused?: string | null }>(
        '/api/retention/redeem',
        { offer_id: offerId, idempotency_key: `demo-offer-${offerId}` });
      show(res.replay
        ? `Duplicate redemption detected — original result returned (AED ${res.amount_aed}); nothing was charged twice.`
        : `Redeemed: AED ${res.amount_aed} discount recorded.${res.auto_paused ? ` Campaign auto-paused (${res.auto_paused}).` : ''}`,
        { variant: res.replay ? 'info' : 'success' });
      await openCampaign(selected.id);
      await load();
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Redemption refused', { variant: 'error' });
    } finally { setBusy(false); }
  };

  const loadOutcomes = async () => {
    if (!selected) return;
    try {
      setOutcomes(await apiGet<Outcomes>(`/api/retention/campaigns/${selected.id}/outcomes`));
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Failed to load outcomes', { variant: 'error' });
    }
  };

  if (!isMarketing) {
    return (
      <main className="min-h-screen p-4 md:p-8"><div className="max-w-3xl mx-auto">
        <Card padding="none">
          <NoPermissionState
            title="Marketing access required"
            description="Retention campaigns need the promotions permission. Ask a workspace admin if you need access."
          />
        </Card>
      </div></main>
    );
  }

  const sim = selected?.simulation ?? null;
  const budgetRemaining = selected
    ? (Number(selected.discount_budget_aed) - Number(selected.budget_spent_aed)).toFixed(2)
    : null;

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <PageHeader
          title="Retention Orchestration"
          description="Churn-risk campaigns with budget, inventory and approval guardrails. All customer data is synthetic demo data."
          icon={<Users className="w-5 h-5" />}
          actions={
            <>
              <Button variant="secondary" size="md" onClick={() => load(true)} aria-label="Refresh">
                <RefreshCw className="w-4 h-4" /> Refresh
              </Button>
              <Button variant="primary" size="md" onClick={() => setShowCreate(v => !v)}>
                <Plus className="w-4 h-4" /> New campaign
              </Button>
            </>
          }
        />

        {showCreate && (
          <Card>
            <h3 className="text-base font-semibold text-ink mb-4">New retention campaign</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Input id="ret-name" label="Name" value={form.name}
                     onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
              <Select id="ret-objective" label="Objective" value={form.objective}
                      onChange={e => setForm(f => ({ ...f, objective: e.target.value }))}>
                {OBJECTIVES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </Select>
              <Select id="ret-store" label="Store" value={form.store_id}
                      onChange={e => setForm(f => ({ ...f, store_id: e.target.value }))}>
                <option value="">Select store…</option>
                {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
              <Select id="ret-item" label="Item" value={form.item_id}
                      onChange={e => setForm(f => ({ ...f, item_id: e.target.value }))}>
                <option value="">Select item…</option>
                {items.map(i => <option key={i.id} value={i.id}>{i.name}</option>)}
              </Select>
              <Input id="ret-start" label="Starts" type="date" value={form.starts_on}
                     onChange={e => setForm(f => ({ ...f, starts_on: e.target.value }))} />
              <Input id="ret-end" label="Ends" type="date" value={form.ends_on}
                     onChange={e => setForm(f => ({ ...f, ends_on: e.target.value }))} />
              <Input id="ret-budget" label="Discount budget (AED)" type="number" min="0"
                     value={form.discount_budget_aed}
                     onChange={e => setForm(f => ({ ...f, discount_budget_aed: e.target.value }))} />
              <Input id="ret-maxd" label="Max discount %" type="number" min="0" max="90"
                     value={form.max_discount_pct}
                     onChange={e => setForm(f => ({ ...f, max_discount_pct: e.target.value }))} />
              <Input id="ret-minm" label="Min margin %" type="number" min="0" max="95"
                     value={form.min_margin_pct}
                     onChange={e => setForm(f => ({ ...f, min_margin_pct: e.target.value }))} />
              <Input id="ret-ctrl" label="Control group %" type="number" min="0" max="50"
                     value={form.control_pct}
                     onChange={e => setForm(f => ({ ...f, control_pct: e.target.value }))} />
              <Input id="ret-thr" label="Churn threshold (0–1)" type="number" step="0.05" min="0" max="1"
                     value={form.churn_threshold}
                     onChange={e => setForm(f => ({ ...f, churn_threshold: e.target.value }))} />
              <Input id="ret-ss" label="Safety stock (units)" type="number" min="0"
                     value={form.safety_stock_units}
                     onChange={e => setForm(f => ({ ...f, safety_stock_units: e.target.value }))} />
            </div>
            <div className="mt-4 flex gap-2">
              <Button variant="primary" loading={busy}
                      disabled={!form.name || !form.store_id || !form.item_id || !form.starts_on || !form.ends_on}
                      onClick={create}>Create draft</Button>
              <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
            </div>
          </Card>
        )}

        {loading ? <SkeletonCard /> : error ? (
          <ErrorState description={error} onRetry={() => load()} />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Campaign list */}
            <Card className="lg:col-span-1">
              <h3 className="text-base font-semibold text-ink mb-3">Campaigns</h3>
              {campaigns.length === 0 ? (
                <EmptyState title="No campaigns yet"
                            description="Create a retention campaign to start the closed-loop workflow." />
              ) : (
                <ul className="space-y-2">
                  {campaigns.map(c => (
                    <li key={c.id}>
                      <button
                        className={`w-full text-left rounded-xl border p-3 transition-colors ${selected?.id === c.id ? 'border-teal-400 bg-surface-2/60' : 'border-line hover:bg-surface-2/40'}`}
                        onClick={() => openCampaign(c.id)}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium text-ink truncate">{c.name}</span>
                          <Badge variant={STATUS_TONE[c.status] ?? 'neutral'} size="sm">{c.status}</Badge>
                        </div>
                        <p className="text-xs text-ink-muted mt-1">
                          {c.store_name} · {c.item_name} · audience {c.audience_size}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {/* Detail */}
            <div className="lg:col-span-2 space-y-6">
              {!selected ? (
                <Card>
                  <EmptyState title="Select a campaign"
                              description="Pick a campaign to see its audience, simulation, guardrails and outcomes." />
                </Card>
              ) : (
                <>
                  <Card>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h3 className="text-base font-semibold text-ink">{selected.name}</h3>
                        <p className="text-xs text-ink-muted mt-0.5">
                          {selected.starts_on} → {selected.ends_on} · budget AED {selected.discount_budget_aed} ·
                          spent AED {selected.budget_spent_aed} · remaining AED {budgetRemaining}
                        </p>
                      </div>
                      <Badge variant={STATUS_TONE[selected.status] ?? 'neutral'}>{selected.status}</Badge>
                    </div>
                    {selected.paused_reason && (
                      <p role="status" className="mt-3 text-sm rounded-xl bg-rose-50 text-rose-700 p-3">
                        Paused — {selected.paused_reason}
                      </p>
                    )}
                    <div className="mt-4 flex flex-wrap gap-2">
                      {selected.status === 'draft' && (
                        <Button size="sm" loading={busy} onClick={() => act('audience', {}, 'Audience built')}>Build audience</Button>
                      )}
                      {!['draft'].includes(selected.status) && (
                        <Button size="sm" variant="secondary" loading={busy} onClick={runScenario}>
                          Run scenario analysis
                        </Button>
                      )}
                      {selected.status === 'audience_ready' && (
                        <Button size="sm" loading={busy} onClick={() => act('simulate', {}, 'Simulation complete')}>Simulate</Button>
                      )}
                      {selected.status === 'simulated' && (
                        <Button size="sm" loading={busy} onClick={() => act('submit', {}, 'Submitted for approval')}>Submit for approval</Button>
                      )}
                      {selected.status === 'pending_approval' && isApprover && (
                        <Button size="sm" loading={busy} onClick={() => act('approve', {}, 'Approved — budget reserved')}>Approve</Button>
                      )}
                      {selected.status === 'pending_approval' && !isApprover && (
                        <span className="text-xs text-ink-muted self-center">Awaiting an approver (regional manager or admin)</span>
                      )}
                      {selected.status === 'approved' && (
                        <Button size="sm" loading={busy} onClick={() => act('activate', {}, 'Campaign live — offers issued')}>Activate</Button>
                      )}
                      {selected.status === 'active' && (
                        <Button size="sm" variant="secondary" loading={busy}
                                onClick={() => act('pause', { reason: 'manual pause' }, 'Paused')}>Pause</Button>
                      )}
                      {selected.status === 'paused' && (
                        <Button size="sm" loading={busy} onClick={() => act('resume', {}, 'Resumed')}>Resume</Button>
                      )}
                      {['active', 'paused'].includes(selected.status) && (
                        <Button size="sm" variant="secondary" loading={busy}
                                onClick={() => act('complete', {}, 'Completed')}>Complete</Button>
                      )}
                      {['completed', 'measured', 'active', 'paused'].includes(selected.status) && (
                        <Button size="sm" variant="ghost" onClick={loadOutcomes}>Measure outcomes</Button>
                      )}
                      {!['completed', 'measured', 'cancelled'].includes(selected.status) && (
                        <Button size="sm" variant="danger" loading={busy}
                                onClick={() => act('cancel', { reason: 'cancelled by user' }, 'Cancelled — reservations released')}>Cancel</Button>
                      )}
                    </div>
                  </Card>

                  {sim && (
                    <Card>
                      <h3 className="text-base font-semibold text-ink mb-3">Simulation</h3>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                        {[
                          ['Audience', sim.audience],
                          ['Control group', sim.control],
                          ['Offers planned', sim.treated_offers],
                          ['Reminders', sim.reminders],
                          ['Suppressed', sim.suppressed],
                          ['Expected redemptions', sim.expected_redemptions],
                          ['Expected spend (AED)', sim.expected_discount_spend_aed],
                          ['Expected value (AED)', sim.expected_incremental_value_aed],
                          ['ATP units', sim.atp_units],
                          ['Shortfall units', sim.shortfall_units],
                        ].map(([label, value]) => (
                          <div key={String(label)}>
                            <p className="text-xs text-ink-muted uppercase">{label}</p>
                            <p className="text-ink font-semibold">{String(value)}</p>
                          </div>
                        ))}
                      </div>
                      {(sim.substitute || sim.transfer_recommendation || sim.procurement_requisition) && (
                        <div className="mt-4 space-y-1 text-sm text-ink-soft">
                          {sim.substitute && <p>Substitute recommended: <span className="font-medium text-ink">{sim.substitute.name}</span></p>}
                          {sim.transfer_recommendation && (
                            <p>Transfer recommended: {sim.transfer_recommendation.units} units from {sim.transfer_recommendation.from_store}</p>
                          )}
                          {sim.procurement_requisition && (
                            <p>Procurement requisition: {JSON.stringify(sim.procurement_requisition)}</p>
                          )}
                        </div>
                      )}
                      {!sim.budget_sufficient && (
                        <p className="mt-3 text-sm rounded-xl bg-amber-50 text-amber-700 p-3">
                          Expected discount spend exceeds the campaign budget — offers will stop when the budget guardrail hits.
                        </p>
                      )}
                    </Card>
                  )}

                  {pack && (
                    <>
                      {/* Recommendation + data readiness */}
                      <Card>
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <h3 className="text-base font-semibold text-ink">Commercial decision pack</h3>
                            <p className="text-xs text-ink-muted mt-0.5">
                              Objective: {pack.objective} · no-campaign baseline{' '}
                              {pack.baseline_no_campaign.p10 != null
                                ? `P10 ${pack.baseline_no_campaign.p10} / P50 ${pack.baseline_no_campaign.p50} / P90 ${pack.baseline_no_campaign.p90}`
                                : `${pack.baseline_no_campaign.units_over_horizon}`} units
                              · data {pack.data_readiness.status} · confidence {pack.confidence}
                            </p>
                            {pack.baseline_no_campaign.quantiles?.intermittent && (
                              <p className="text-xs text-amber-700 mt-1">
                                Intermittent demand ({(pack.baseline_no_campaign.quantiles.zero_share * 100).toFixed(0)}% zero-demand days) —
                                quantile bands are low-confidence for this SKU.
                              </p>
                            )}
                          </div>
                          <div className="text-right">
                            <Badge variant={DECISION_TONE[pack.recommendation.decision] ?? 'neutral'}>
                              {pack.recommendation.decision}
                            </Badge>
                            {pack.recommendation.chosen && (
                              <p className="text-xs text-ink-muted mt-1">chosen: {pack.recommendation.chosen}</p>
                            )}
                          </div>
                        </div>
                        {pack.recommendation.conditions.length > 0 && (
                          <ul className="mt-3 text-sm text-ink-soft list-disc ps-5 space-y-0.5">
                            {pack.recommendation.conditions.map((c, i) => <li key={i}>{c}</li>)}
                          </ul>
                        )}
                        {(pack.data_readiness.warnings.length > 0 || pack.data_readiness.blockers.length > 0) && (
                          <p className="mt-3 text-xs rounded-xl bg-amber-50 text-amber-700 p-2">
                            {[...pack.data_readiness.blockers, ...pack.data_readiness.warnings].join(', ')}
                          </p>
                        )}
                        <p className="mt-3 text-xs text-ink-muted">
                          Price response, cannibalisation, halo and forward-buy are transparent provisional
                          heuristics (confidence low) on synthetic data — not measured causal effects.
                        </p>
                      </Card>

                      {/* Scenario comparison */}
                      <Card padding="none">
                        <div className="p-4 pb-0">
                          <h3 className="text-base font-semibold text-ink">Scenario comparison (low / expected / high)</h3>
                        </div>
                        <div className="overflow-x-auto p-4">
                          <Table>
                            <TableHead>
                              <TableRow>
                                <Th>Offer</Th><Th>Demand L/E/H</Th><Th>Net category</Th>
                                <Th>Stock risk</Th><Th>Profit P10/P50/P90 (AED)</Th>
                                <Th>CVaR 5%</Th><Th>Loss prob.</Th>
                                <Th>Risk-adj value</Th><Th>Policy</Th>
                              </TableRow>
                            </TableHead>
                            <TableBody>
                              {pack.scenarios.map(s => {
                                const isChosen = s.label === pack.recommendation.chosen;
                                return (
                                  <TableRow key={s.label} className={isChosen ? 'bg-teal-50' : ''}>
                                    <Td>
                                      <span className="font-medium text-ink">{s.label}</span>
                                      {isChosen && <Badge size="sm" variant="teal" className="ms-2">recommended</Badge>}
                                    </Td>
                                    <Td>{s.demand_low}/{s.demand_expected}/{s.demand_high}</Td>
                                    <Td>{s.category.net_incremental_category_units}
                                      <span className="block text-xs text-ink-muted">
                                        cann −{s.category.cannibalized_units} · halo +{s.category.halo_units} · fwd −{s.category.forward_bought_units}
                                      </span>
                                    </Td>
                                    <Td>{s.monte_carlo && s.monte_carlo.stockout_probability > 0
                                      ? <Badge size="sm" variant="danger">stockout {(s.monte_carlo.stockout_probability * 100).toFixed(0)}%</Badge>
                                      : s.inventory.expected_expiry_units > 0
                                        ? <Badge size="sm" variant="amber">expiry {s.inventory.expected_expiry_units}</Badge>
                                        : <span className="text-ink-muted text-xs">ok</span>}
                                    </Td>
                                    <Td>{s.monte_carlo
                                      ? `${s.monte_carlo.profit_p10_aed}/${s.monte_carlo.profit_p50_aed}/${s.monte_carlo.profit_p90_aed}`
                                      : `${s.finance.net_profit_low_aed}/${s.finance.net_profit_expected_aed}/${s.finance.net_profit_high_aed}`}</Td>
                                    <Td>{s.monte_carlo?.cvar_5pct_aed ?? s.finance.worst_credible_loss_aed}</Td>
                                    <Td>{s.monte_carlo
                                      ? <Badge size="sm" variant={s.monte_carlo.loss_probability > 0.2 ? 'danger' : s.monte_carlo.loss_probability > 0.05 ? 'amber' : 'success'}>
                                          {(s.monte_carlo.loss_probability * 100).toFixed(1)}%
                                        </Badge>
                                      : '—'}</Td>
                                    <Td className="font-medium">{s.risk_adjusted.risk_adjusted_value_aed}</Td>
                                    <Td>{s.policy_ok
                                      ? <span className="text-emerald-600 text-xs">ok</span>
                                      : <Badge size="sm" variant="danger">{s.policy_reason}</Badge>}
                                    </Td>
                                  </TableRow>
                                );
                              })}
                            </TableBody>
                          </Table>
                        </div>
                      </Card>

                      {/* Chosen scenario: procurement options + conflicts */}
                      {(() => {
                        const chosen = pack.scenarios.find(s => s.label === pack.recommendation.chosen)
                          ?? pack.scenarios[pack.scenarios.length - 1];
                        if (!chosen) return null;
                        return (
                          <Card>
                            <h3 className="text-base font-semibold text-ink mb-3">
                              Fulfilment options &amp; conflicts — {chosen.label}
                            </h3>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div>
                                <p className="text-xs text-ink-muted uppercase mb-1">Procurement / fulfilment options</p>
                                <ul className="space-y-1 text-sm">
                                  {chosen.procurement_options.map((o, i) => (
                                    <li key={i} className="flex items-center gap-2">
                                      <Badge size="sm" variant={o.option === 'no_buy' ? 'neutral' : o.in_time === false ? 'danger' : 'teal'}>{o.option}</Badge>
                                      <span className="text-ink-soft">{o.units > 0 ? `${o.units} units · AED ${o.cost_aed}` : ''} {o.note}</span>
                                    </li>
                                  ))}
                                </ul>
                                <p className="mt-2 text-xs text-ink-muted">No purchase order is created during simulation.</p>
                              </div>
                              <div>
                                <p className="text-xs text-ink-muted uppercase mb-1">Conflicts detected</p>
                                {chosen.conflicts.length === 0 ? (
                                  <p className="text-sm text-ink-muted">None</p>
                                ) : (
                                  <ul className="space-y-2 text-sm">
                                    {chosen.conflicts.map(c => (
                                      <li key={c.code} className="rounded-xl bg-surface-2/60 p-2">
                                        <span className="font-medium text-ink">{c.code}</span>
                                        {c.blocks_campaign && <Badge size="sm" variant="danger" className="ms-2">blocks</Badge>}
                                        <span className="block text-xs text-ink-muted">{c.evidence} → {c.resolution} ({c.required_approver})</span>
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </div>
                            </div>
                          </Card>
                        );
                      })()}

                      {/* Department review cards */}
                      <Card>
                        <h3 className="text-base font-semibold text-ink mb-3">Department review</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                          {DEPT_ORDER.filter(d => pack.department_views[d]).map(d => (
                            <div key={d} className="rounded-xl border border-line p-3">
                              <p className="text-xs font-semibold text-ink uppercase">{d.replace('_', ' ')}</p>
                              <p className="text-sm text-ink-soft mt-1">{pack.department_views[d].headline}</p>
                              {pack.department_views[d].reason_codes.length > 0 && (
                                <p className="mt-1 text-xs text-ink-muted">{pack.department_views[d].reason_codes.join(', ')}</p>
                              )}
                            </div>
                          ))}
                        </div>
                      </Card>
                    </>
                  )}

                  {offers.length > 0 && (
                    <Card padding="none">
                      <div className="p-4 pb-0 flex items-center justify-between">
                        <h3 className="text-base font-semibold text-ink">Decision trace ({offers.length})</h3>
                        <Badge variant="amber" size="sm">synthetic data</Badge>
                      </div>
                      <div className="overflow-x-auto p-4">
                        <Table>
                          <TableHead>
                            <TableRow>
                              <Th>Customer</Th><Th>Cohort</Th><Th>Churn</Th><Th>Action</Th>
                              <Th>Disc%</Th><Th>EV (AED)</Th><Th>Status</Th><Th>Reasons</Th><Th></Th>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {offers.slice(0, 50).map(o => (
                              <TableRow key={o.id}>
                                <Td>
                                  <span className="font-medium text-ink">{o.customer_ref}</span>
                                  <span className="block text-xs text-ink-muted">{o.archetype}</span>
                                </Td>
                                <Td><Badge size="sm" variant={o.cohort === 'control' ? 'neutral' : 'teal'}>{o.cohort}</Badge></Td>
                                <Td>{o.churn_score}</Td>
                                <Td>{o.action}</Td>
                                <Td>{Number(o.discount_pct) > 0 ? o.discount_pct : '—'}</Td>
                                <Td>{o.expected_value_aed}</Td>
                                <Td><Badge size="sm" variant={o.status === 'redeemed' ? 'success' : o.status === 'issued' ? 'amber' : 'neutral'}>{o.status}</Badge></Td>
                                <Td><span className="text-xs text-ink-muted">{(o.reason_codes ?? []).join(', ')}</span></Td>
                                <Td>
                                  {o.status === 'issued' && (
                                    <Button size="sm" variant="secondary" loading={busy}
                                            onClick={() => redeemOffer(o.id)}>Redeem</Button>
                                  )}
                                </Td>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </Card>
                  )}

                  {outcomes && (
                    <Card>
                      <h3 className="text-base font-semibold text-ink mb-3">Treatment vs control</h3>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                        <div><p className="text-xs text-ink-muted uppercase">Treatment n</p>
                          <p className="text-ink font-semibold">{outcomes.treatment.n}</p></div>
                        <div><p className="text-xs text-ink-muted uppercase">Treatment purchase rate</p>
                          <p className="text-ink font-semibold">{(outcomes.treatment.purchase_rate * 100).toFixed(1)}%</p></div>
                        <div><p className="text-xs text-ink-muted uppercase">Control purchase rate</p>
                          <p className="text-ink font-semibold">{(outcomes.control.purchase_rate * 100).toFixed(1)}%</p></div>
                        <div><p className="text-xs text-ink-muted uppercase">Incremental</p>
                          <p className="text-ink font-semibold">{(outcomes.incremental_purchase_rate * 100).toFixed(1)}%</p></div>
                        <div><p className="text-xs text-ink-muted uppercase">Redemptions</p>
                          <p className="text-ink font-semibold">{outcomes.treatment.redemptions}</p></div>
                        <div><p className="text-xs text-ink-muted uppercase">Discount spend (AED)</p>
                          <p className="text-ink font-semibold">{outcomes.treatment.discount_spend_aed}</p></div>
                        <div><p className="text-xs text-ink-muted uppercase">Budget spent (AED)</p>
                          <p className="text-ink font-semibold">{outcomes.budget.spent_aed}</p></div>
                      </div>
                      <p className="mt-3 text-xs text-ink-muted">
                        Randomized split on synthetic demo data at demo scale — mechanics demonstration, not a causal claim.
                      </p>
                    </Card>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
