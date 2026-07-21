/**
 * Flywheel API facade — typed endpoints over the shared apiClient.
 *
 * Follows the same shape as lib/api.ts: this module maps endpoints to cache
 * TTLs and types; auth, CSRF, refresh-retry and the authorization-scoped cache
 * all live in apiClient.
 *
 * TTL POLICY. Money and live state get SHORT or zero TTLs. Serving a cached
 * budget balance is how an operator approves spend against a number that is no
 * longer true, so `budget`, `live` and anything decision-shaped are never cached.
 */
import { apiRequest, clearApiCache } from './apiClient';
import type {
  ApprovalRequestDetail, ApprovalRequestSummary, AtpSnapshot, AudienceResult,
  DataTrustReport,
  BudgetOverview, CampaignDetail, CampaignSummary, CustomerDetail, DecisionTrace,
  EvaluateResult, FlywheelCustomer, FlywheelHealth, LiveMetrics, MeasurementResult,
  ModelVersion, RedeemResult, Requisition, SimulationResult,
  AllocationRun, CampaignHoldout, CampaignReadout, GovernanceOverview,
  HoldoutOverview, IncrementalitySummary, Preregistration, ReadoutPoint,
  ShadowComparisonRow, ShadowOverview,
  CannibalizationResult, MeteringSummary, SupplierDashboard, TradeOverview,
  CoalitionAttribution, OutcomePricingStatus, SeasonalityCalendar, ShelfLifeResult,
} from '@/types/flywheel';

const TTL = {
  campaigns: 10_000,
  customers: 30_000,
  models: 120_000,
  health: 15_000,
  /** Money and live state are NEVER served from cache. */
  none: 0,
} as const;

/** Format an AED string from the API for display, without float arithmetic. */
export function aed(value: string | number | null | undefined, opts?: { compact?: boolean }): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = typeof value === 'number' ? value : Number.parseFloat(value);
  if (Number.isNaN(n)) return '—';
  if (opts?.compact && Math.abs(n) >= 1000) {
    return `${new Intl.NumberFormat('en-AE', { maximumFractionDigits: 1 }).format(n / 1000)}k`;
  }
  return new Intl.NumberFormat('en-AE', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(n);
}

/** Percentage from a 0–1 ratio. */
export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

export function clearFlywheelCache(): void {
  clearApiCache('flywheel');
}

// ── Stage 1: data ──────────────────────────────────────────────────────────

export const seedCustomers = (body: {
  customer_count?: number; history_days?: number; seed?: number; force?: boolean;
}) => apiRequest<{ success: boolean; created: number; events: number; skipped: boolean }>(
  '/api/flywheel/seed', { method: 'POST', body });

export const fetchCustomers = (params?: { risk_band?: string; limit?: number; offset?: number }) =>
  apiRequest<{ customers: FlywheelCustomer[]; synthetic: boolean; disclaimer: string }>(
    '/api/flywheel/customers', { params, ttl: TTL.customers });

export const fetchCustomer = (id: number) =>
  apiRequest<CustomerDetail>(`/api/flywheel/customers/${id}`, { ttl: TTL.customers });

// ── Stage 2: intelligence ──────────────────────────────────────────────────

export const buildFeatures = (as_of?: string) =>
  apiRequest<{ snapshots: number; as_of: string; features: string[] }>(
    '/api/flywheel/features/build', { method: 'POST', params: as_of ? { as_of } : undefined });

export const scoreChurn = (as_of?: string) =>
  apiRequest<{ scored: number; tier: string; risk_bands: Record<string, number>; model_version: string }>(
    '/api/flywheel/churn/score', { method: 'POST', params: as_of ? { as_of } : undefined });

export const fetchModels = () =>
  apiRequest<{ models: ModelVersion[]; honesty_note: string }>(
    '/api/flywheel/models', { ttl: TTL.models });

// ── Stage 3–4: campaigns ───────────────────────────────────────────────────

export const createCampaign = (body: Record<string, unknown>) =>
  apiRequest<{ campaign_id: number; status: string; name: string }>(
    '/api/flywheel/campaigns', { method: 'POST', body });

export const fetchCampaigns = (status?: string) =>
  apiRequest<{ campaigns: CampaignSummary[] }>(
    '/api/flywheel/campaigns', { params: status ? { status } : undefined, ttl: TTL.campaigns });

export const fetchCampaign = (id: number) =>
  apiRequest<CampaignDetail>(`/api/flywheel/campaigns/${id}`, { ttl: TTL.campaigns });

export const buildAudience = (id: number, body: { min_churn_probability?: number; max_size?: number }) =>
  apiRequest<AudienceResult>(`/api/flywheel/campaigns/${id}/audience`, { method: 'POST', body });

export const simulateCampaign = (id: number, sample_size = 400) =>
  apiRequest<SimulationResult>(`/api/flywheel/campaigns/${id}/simulate`,
    { method: 'POST', params: { sample_size } });

/** The data-trust verdict for a campaign. Read-only, and the same gate the
 *  server enforces on simulate/activate — so the studio can show WHY something
 *  will be refused before the operator spends effort hitting the refusal. */
export const fetchCampaignDataTrust = (id: number) =>
  apiRequest<DataTrustReport>(`/api/flywheel/campaigns/${id}/data-trust`);

export const submitCampaign = (id: number) =>
  apiRequest<{ request_id: number; step_count: number; campaign_status: string; simulation: SimulationResult }>(
    `/api/flywheel/campaigns/${id}/submit`, { method: 'POST' });

export const activateCampaign = (id: number) =>
  apiRequest<{ campaign_id: number; status: string; reserved_aed: string; soft_allocations: number }>(
    `/api/flywheel/campaigns/${id}/activate`, { method: 'POST' });

export const pauseCampaign = (id: number, reason: string) =>
  apiRequest<{ status: string; reason: string }>(
    `/api/flywheel/campaigns/${id}/pause`, { method: 'POST', params: { reason } });

export const resumeCampaign = (id: number) =>
  apiRequest<{ status: string }>(`/api/flywheel/campaigns/${id}/resume`, { method: 'POST' });

export const concludeCampaign = (id: number, cancel = false) =>
  apiRequest<{ status: string }>(
    `/api/flywheel/campaigns/${id}/conclude`, { method: 'POST', params: { cancel } });

// ── Stage 4: inventory, procurement, budget, approvals ─────────────────────

export const fetchAtp = (store_id: number, item_id: number, safety_stock_pct = 10) =>
  apiRequest<AtpSnapshot>('/api/flywheel/inventory/atp',
    { params: { store_id, item_id, safety_stock_pct } });

export const fetchRequisitions = (campaignId: number) =>
  apiRequest<{ requisitions: Requisition[] }>(`/api/flywheel/campaigns/${campaignId}/procurement`);

export const convertRequisition = (id: number) =>
  apiRequest<{ purchase_order_id: number; po_number?: string; created: boolean }>(
    `/api/flywheel/requisitions/${id}/convert`, { method: 'POST' });

/** Never cached — approving spend against a stale balance is a real failure. */
export const fetchBudget = () => apiRequest<BudgetOverview>('/api/flywheel/budget');

export const fetchApprovals = (status = 'pending') =>
  apiRequest<{ requests: ApprovalRequestSummary[] }>('/api/flywheel/approvals', { params: { status } });

export const fetchApproval = (id: number) =>
  apiRequest<ApprovalRequestDetail>(`/api/flywheel/approvals/${id}`);

export const decideApproval = (stepId: number, decision: string, comment?: string) =>
  apiRequest<{ applied: boolean; request_status: string; fully_approved: boolean }>(
    `/api/flywheel/approvals/steps/${stepId}/decide`, { method: 'POST', body: { decision, comment } });

// ── Stage 5: decisioning ───────────────────────────────────────────────────

export const evaluateDecision = (body: {
  customer_id: number; store_id: number; channel?: string;
  cart_items?: number[]; campaign_id?: number; issue_offer?: boolean;
}) => apiRequest<EvaluateResult>('/api/flywheel/decisioning/evaluate', { method: 'POST', body });

export const redeemOffer = (body: {
  offer_code: string; units: number; idempotency_key: string; store_id?: number;
}) => apiRequest<RedeemResult>('/api/flywheel/decisioning/redeem', { method: 'POST', body });

export const fetchDecisionTrace = (id: number) =>
  apiRequest<DecisionTrace>(`/api/flywheel/decisions/${id}`);

// ── Stage 5–6: live & measurement ──────────────────────────────────────────

export const fetchLive = (id: number) => apiRequest<LiveMetrics>(`/api/flywheel/campaigns/${id}/live`);

export const measureCampaign = (id: number) =>
  apiRequest<MeasurementResult>(`/api/flywheel/campaigns/${id}/measure`, { method: 'POST' });

export const fetchOutcome = (id: number) =>
  apiRequest<MeasurementResult>(`/api/flywheel/campaigns/${id}/outcome`);

export const fetchHealth = () => apiRequest<FlywheelHealth>('/api/flywheel/health', { ttl: TTL.health });

// ── Presentation helpers ───────────────────────────────────────────────────

/** Campaign status → badge tone, matching the existing Badge variants. */
export const STATUS_TONE: Record<string, 'neutral' | 'teal' | 'amber' | 'violet' | 'success' | 'danger'> = {
  DRAFT: 'neutral', AUDIENCE_READY: 'neutral', SIMULATED: 'violet',
  PENDING_INVENTORY_REVIEW: 'amber', PENDING_PROCUREMENT_REVIEW: 'amber',
  PENDING_FINANCE_APPROVAL: 'amber', PENDING_MARKETING_APPROVAL: 'amber',
  APPROVED: 'teal', SCHEDULED: 'teal', ACTIVE: 'success',
  PAUSED: 'danger', COMPLETED: 'neutral', CANCELLED: 'neutral', MEASURED: 'violet',
};

export const RISK_TONE: Record<string, 'success' | 'amber' | 'danger' | 'neutral'> = {
  low: 'success', medium: 'amber', high: 'danger', critical: 'danger', };

/**
 * Human-readable reason codes. The backend emits stable machine codes; this map
 * is the single place they become sentences, so the wording stays consistent
 * across the Decision Trace, the simulation panel and the live centre.
 */
export const REASON_TEXT: Record<string, string> = {
  POSITIVE_EIV: 'Expected value is positive',
  HIGH_CHURN_RISK: 'Customer is at high risk of leaving',
  STRONG_UPLIFT: 'An offer is likely to change the outcome',
  CHEAPEST_EFFECTIVE_ACTION: 'Cheapest action that still wins',
  BASELINE_DO_NOTHING: 'Baseline — take no action',
  NO_VIABLE_ACTION: 'No action beat doing nothing',
  NEGATIVE_EIV: 'Costs more than it returns',
  NEGATIVE_UPLIFT: 'An offer would make things worse',
  UPLIFT_BELOW_THRESHOLD: 'Uplift is within noise — risk alone does not justify a discount',
  MARGIN_FLOOR_BREACHED: 'Would sell below the margin floor',
  DISCOUNT_CAP_EXCEEDED: 'Exceeds the campaign discount cap',
  INSUFFICIENT_STOCK: 'Not enough stock available to promise',
  INSUFFICIENT_BUDGET: 'Discount budget is exhausted',
  NO_CONSENT: 'Customer has not consented on this channel',
  CONTACT_CAP_REACHED: 'Contact-frequency cap already reached',
  CONTROL_GROUP: 'Control group — measured but never treated',
  CAMPAIGN_NOT_ACTIVE: 'No active campaign covers this customer',
  OUT_OF_SCOPE: 'Outside your tenant or store scope',
  NO_PRICE_DATA: 'No price data for this item',
  PROCUREMENT_TOO_SLOW: 'Stock would arrive after it is needed',
  PROCUREMENT_UNECONOMIC: 'Buying stock would make the campaign lose money',
  STALE_DATA: 'Inventory data is too stale to promise against',
  EXPLANATION_INDICATIVE: 'Trained model differs from the rule baseline — drivers are indicative',
  OVERDUE_VS_OWN_CADENCE: 'Overdue against their own buying rhythm',
  VERY_LOW_FREQUENCY: 'Very few purchases recently',
  SPEND_DECLINING: 'Spending less than they used to',
  ERRATIC_CADENCE: 'Buying pattern has become erratic',
  SINGLE_CATEGORY_ONLY: 'Shops a single category only',
  HIGH_RETURN_RATIO: 'High proportion of returns',
  STABLE_BEHAVIOUR: 'No deterioration detected',
};

export const reasonText = (code: string): string =>
  REASON_TEXT[code] ?? code.replace(/_/g, ' ').toLowerCase();

/** The shortage ladder, in order, for rendering resolution paths. */
export const LADDER_LABELS: Record<string, string> = {
  none: 'Stock sufficient',
  a_reduce_audience: 'Reduce audience',
  b_substitute: 'In-stock substitute',
  c_transfer: 'Inter-store transfer',
  d_non_stock_reward: 'Non-inventory reward',
  e_procurement: 'Procurement requisition',
  f_suppress: 'Suppress offer',
};

// ── Horizon 1: proving it ──────────────────────────────────────────────────
//
// NONE of these are cached. A readout is evidence and a balance check is a
// safety diagnostic; serving either from cache would let an operator act on a
// number that has since moved, which is the exact failure the money endpoints
// already avoid.

export const fetchIncrementality = () =>
  apiRequest<IncrementalitySummary>('/api/flywheel/incrementality', { ttl: TTL.none });

export const fetchCampaignReadout = (id: number) =>
  apiRequest<CampaignReadout>(`/api/flywheel/campaigns/${id}/readout`, { ttl: TTL.none });

export const fetchReadoutHistory = (id: number, limit = 90) =>
  apiRequest<{ campaign_id: number; series: ReadoutPoint[]; note: string }>(
    `/api/flywheel/campaigns/${id}/readout/history?limit=${limit}`, { ttl: TTL.none });

export const recomputeReadout = (id: number) =>
  apiRequest<Record<string, unknown>>(
    `/api/flywheel/campaigns/${id}/readout/recompute`, { method: 'POST' });

export const fetchPreregistration = (id: number) =>
  apiRequest<Preregistration & { preregistered: boolean; warning?: string }>(
    `/api/flywheel/campaigns/${id}/preregistration`, { ttl: TTL.none });

export const createPreregistration = (id: number, body: Record<string, unknown>) =>
  apiRequest<Preregistration>(`/api/flywheel/campaigns/${id}/preregistration`,
    { method: 'POST', body: JSON.stringify(body) });

export const fetchCampaignHoldout = (id: number) =>
  apiRequest<CampaignHoldout>(`/api/flywheel/campaigns/${id}/holdout`, { ttl: TTL.none });

export const fetchHoldoutOverview = () =>
  apiRequest<HoldoutOverview>('/api/flywheel/holdout', { ttl: TTL.none });

export const fetchGovernance = () =>
  apiRequest<GovernanceOverview>('/api/flywheel/governance', { ttl: TTL.none });

export const fetchShadow = () =>
  apiRequest<ShadowOverview>('/api/flywheel/models/shadow', { ttl: TTL.none });

export const runShadowScore = () =>
  apiRequest<{ scored: number; comparison: ShadowComparisonRow[] }>(
    '/api/flywheel/models/shadow/score', { method: 'POST' });

export const fetchAllocationRuns = (id: number) =>
  apiRequest<{ campaign_id: number; runs: AllocationRun[]; note: string }>(
    `/api/flywheel/campaigns/${id}/allocation`, { ttl: TTL.none });

/** Tone for a readout state. `inconclusive` is deliberately NEUTRAL, never a
 *  warning colour — "still measuring" is not a problem to be fixed. */
export const READOUT_TONE: Record<string, 'neutral' | 'success' | 'amber' | 'danger'> = {
  not_measurable: 'neutral',
  inconclusive: 'neutral',
  significant_but_small: 'amber',
  significant: 'success',
};

// ── Horizon 3: two tracks ───────────────────────────────────────────────────

export const fetchTradeOverview = () =>
  apiRequest<TradeOverview>('/api/flywheel/trade', { ttl: TTL.none });

export const fetchSupplierDashboard = (supplierId: number) =>
  apiRequest<SupplierDashboard>(`/api/flywheel/suppliers/${supplierId}/dashboard`, { ttl: TTL.none });

export const fetchCannibalization = (campaignId: number) =>
  apiRequest<CannibalizationResult>(`/api/flywheel/campaigns/${campaignId}/cannibalization`, { ttl: TTL.none });

export const recomputeCannibalization = (campaignId: number) =>
  apiRequest<Record<string, unknown>>(
    `/api/flywheel/campaigns/${campaignId}/cannibalization/recompute`, { method: 'POST' });

export const fetchMetering = () =>
  apiRequest<MeteringSummary>('/api/flywheel/metering', { ttl: TTL.none });

/** Funding-status tone for badges. */
export const FUNDING_TONE: Record<string, 'neutral' | 'amber' | 'teal' | 'success' | 'danger'> = {
  proposed: 'neutral', committed: 'teal', active: 'success',
  settled: 'success', disputed: 'danger', cancelled: 'neutral',
};

// ── Horizon 4: expand ────────────────────────────────────────────────────────

export const fetchSeasonality = () =>
  apiRequest<SeasonalityCalendar>('/api/flywheel/seasonality', { ttl: TTL.none });

export const fetchShelfLife = (storeId?: number) =>
  apiRequest<ShelfLifeResult>(
    `/api/flywheel/shelf-life${storeId ? `?store_id=${storeId}` : ''}`, { ttl: TTL.none });

export const fetchCoalitionAttribution = (campaignId: number) =>
  apiRequest<CoalitionAttribution>(`/api/flywheel/campaigns/${campaignId}/coalition`, { ttl: TTL.none });

export const fetchOutcomePricing = () =>
  apiRequest<OutcomePricingStatus>('/api/flywheel/outcome-pricing', { ttl: TTL.none });

/** Partner-type tone for badges. */
export const PARTNER_TONE: Record<string, 'neutral' | 'teal' | 'amber' | 'violet' | 'success'> = {
  grocery: 'success', fuel: 'amber', hospitality: 'violet', travel: 'teal',
  retail: 'neutral', dining: 'violet', other: 'neutral',
};
