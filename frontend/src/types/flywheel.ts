/**
 * Flywheel types — mirror the backend contracts in app/routes/flywheel.py.
 *
 * MONEY IS A STRING, NOT A NUMBER. Every AED value crosses the wire as a string
 * because the backend holds it as a Postgres NUMERIC / Python Decimal, and
 * JSON numbers are IEEE-754 doubles. Parsing "1234567.89" into a float and back
 * is how a ledger drifts by fils. Use `aed()` from lib/flywheel to format for
 * display, and never do arithmetic on these client-side — ask the backend.
 */

export type CampaignStatus =
  | 'DRAFT' | 'AUDIENCE_READY' | 'SIMULATED'
  | 'PENDING_INVENTORY_REVIEW' | 'PENDING_PROCUREMENT_REVIEW'
  | 'PENDING_FINANCE_APPROVAL' | 'PENDING_MARKETING_APPROVAL'
  | 'APPROVED' | 'SCHEDULED' | 'ACTIVE' | 'PAUSED'
  | 'COMPLETED' | 'CANCELLED' | 'MEASURED';

export type ActionType =
  | 'NO_ACTION' | 'REMINDER' | 'LOYALTY_POINTS' | 'FREE_DELIVERY'
  | 'PERCENT_DISCOUNT' | 'FIXED_DISCOUNT' | 'PRODUCT_BUNDLE'
  | 'SUBSTITUTE_PRODUCT' | 'ALTERNATIVE_STORE' | 'HUMAN_REVIEW';

export type RiskBand = 'low' | 'medium' | 'high' | 'critical';

export interface CampaignSummary {
  id: number;
  name: string;
  objective: string;
  status: CampaignStatus;
  starts_on: string;
  ends_on: string;
  discount_budget_aed: string;
  control_group_pct: number;
  pause_reason: string | null;
  created_at: string | null;
  treatment_size: number;
  control_size: number;
  redemptions: number;
}

export interface CampaignDetail {
  campaign: {
    id: number; name: string; objective: string; status: CampaignStatus;
    starts_on: string; ends_on: string; channel: string;
    max_discount_pct: number; min_margin_pct: number;
    discount_budget_aed: string; procurement_budget_aed: string;
    safety_stock_pct: number; control_group_pct: number;
    contact_cap_per_week: number; audience_spec: Record<string, unknown>;
    policy_version: string; pause_reason: string | null;
    activated_at: string | null; created_at: string | null;
  };
  allowed_transitions: CampaignStatus[];
  history: Array<{
    from: string | null; to: string; actor_kind: string;
    reason: string | null; at: string; actor: string | null;
  }>;
  audience: Record<string, { size: number; avg_churn: number | null }>;
  budget_exposure: BudgetExposure;
}

export interface BudgetExposure {
  reserved_aed: string;
  spent_aed: string;
  released_aed: string;
  committed_aed: string;
  outstanding_aed: string;
}

export interface AudienceResult {
  campaign_id: number;
  total: number;
  treatment: number;
  control: number;
  control_pct_actual: number;
  control_pct_target: number;
  as_of: string;
  min_churn_probability: number;
}

export interface Scenario {
  discount_spend_aed: string;
  incremental_margin_aed: string;
  retained_value_aed: string;
  net_value_aed: string;
  roi: string;
}

export interface Shortage {
  store_id: number;
  item_id: number;
  required_units: number;
  atp_units: number;
  shortage_units: number;
  required_by: string;
  expected_eiv_aed: string;
}

export interface ShortageResolution {
  store_id: number;
  item_id: number;
  rung: string;
  resolved: boolean;
  detail: string;
  substitute?: { item_id: number; name: string; unit_price_aed: string; atp_units: number; reason: string };
  transfer?: { from_store_id: number; from_store_name: string; units: number; source_surplus_units: number; reason: string };
  procurement?: Record<string, unknown>;
  procurement_rejected?: { reason_code: string; detail: string };
  atp?: AtpSnapshot;
}

/** Is the input data fit to decide on? Returned by the data-trust gate, which
 *  simulate() and activate() also enforce server-side. */
export type DataTrustStatus = 'READY' | 'READY_WITH_WARNINGS' | 'NOT_READY';

export interface DataTrustFinding {
  code: string;
  severity: 'block' | 'warn';
  detail: string;
  evidence: Record<string, unknown>;
}

export interface DataTrustReport {
  status: DataTrustStatus;
  campaign_id: number | null;
  findings: DataTrustFinding[];
  blockers: string[];
  warnings: string[];
  scope: { stores_evaluated: number; items_evaluated: number };
  thresholds: Record<string, number>;
}

/** Distribution-based view of the simulation: a lognormal response multiplier
 *  sampled many times, rather than the fixed 0.6x/1.0x/1.4x scenario band.
 *  Optional because a campaign simulated before this shipped has no block. */
export interface SimulationUncertainty {
  trials: number;
  net_value_p10_aed: string;
  net_value_p50_aed: string;
  net_value_p90_aed: string;
  net_value_mean_aed: string;
  cvar_5pct_aed: string;
  loss_probability: number;
  expected_spend_aed: string;
  roi_mean: string;
  response_cv: number;
  method: string;
}

export interface SimulationResult {
  campaign_id: number;
  audience: { treatment_total: number; sampled: number; scale_factor: number; note: string };
  expected_redemptions: number;
  action_mix: Record<string, number>;
  scenarios: { pessimistic: Scenario; expected: Scenario; optimistic: Scenario };
  uncertainty?: SimulationUncertainty;
  /** How far the numbers above can be trusted. Optional: campaigns simulated
   *  before the gate shipped carry no report. */
  data_trust?: DataTrustReport;
  discount_budget_declared_aed: string;
  budget_sufficient: boolean;
  inventory: { skus_evaluated: number; shortages: Shortage[]; resolutions: ShortageResolution[] };
  policy_version: string;
  synthetic: boolean;
}

export interface AtpSnapshot {
  store_id: number;
  item_id: number;
  on_hand: number;
  incoming: number;
  hard_reservations: number;
  soft_allocations: number;
  safety_stock: number;
  demand_buffer: number;
  atp_units: number;
  formula?: string;
}

export interface ApprovalStep {
  step_id: number;
  step_order: number;
  label: string;
  required_role: string;
  required_permission: string | null;
  status: 'pending' | 'approved' | 'rejected' | 'changes_requested' | 'skipped';
  comment: string | null;
  decided_at: string | null;
  decided_by: string | null;
  parallel_group: number;
  can_decide?: boolean;
}

export interface ApprovalRequestSummary {
  request_id: number;
  request_type: string;
  status: string;
  discount_exposure_aed: string;
  procurement_exposure_aed: string;
  expected_roi: number | null;
  created_at: string | null;
  expires_at: string | null;
  campaign_id: number | null;
  campaign_name: string | null;
  awaiting: string[];
  can_act: boolean;
}

export interface ApprovalRequestDetail extends Omit<ApprovalRequestSummary, 'awaiting' | 'can_act'> {
  summary: Record<string, unknown>;
  requested_by: string | null;
  steps: ApprovalStep[];
  progress: { approved: number; total: number; pct: number };
}

export interface BudgetSnapshot {
  budget_id: number;
  budget_type: string;
  currency: string;
  allocated_aed: string;
  reserved_aed: string;
  committed_aed: string;
  spent_aed: string;
  released_aed: string;
  available_aed: string;
  period_start: string;
  period_end: string;
}

export interface LedgerEntry {
  entry_type: 'ALLOCATED' | 'RESERVED' | 'COMMITTED' | 'SPENT' | 'RELEASED';
  amount_aed: string;
  source_type: string;
  at: string;
  balance_before: string;
  balance_after: string;
  reason: string | null;
  campaign: string | null;
  actor: string | null;
}

export interface BudgetOverview {
  budgets: BudgetSnapshot[];
  ledger: LedgerEntry[];
  cash_requirement_by_date: Array<{ date: string; amount_aed: string }>;
}

export interface Requisition {
  id: number;
  store_id: number; store_name: string;
  item_id: number; item_name: string;
  supplier: string | null;
  shortage_units: number; order_units: number;
  unit_cost_aed: string; total_cost_aed: string;
  lead_time_days: number;
  required_by: string; expected_arrival: string | null;
  status: string;
  justification: Record<string, unknown>;
  purchase_order_id: number | null;
}

export interface RejectedAction {
  action: string;
  discount_pct?: string;
  reason_code: string;
  detail?: string;
  eiv_aed?: string;
}

export interface EvaluateResult {
  action: ActionType;
  decision_id: number | null;
  campaign_id?: number;
  offer: {
    offer_id: number; offer_code: string; action: string; discount_pct: string;
    item_id: number | null; store_id: number; unit_price_aed: string; expires_at: string;
  } | null;
  reason_codes: string[];
  rejected_actions?: RejectedAction[];
  detail?: string;
  eiv_aed?: string;
  churn_probability?: number;
  uplift?: number;
  inventory_status?: AtpSnapshot;
  budget_status?: Partial<BudgetSnapshot>;
  model_version?: string;
  policy_version?: string;
  message_key: string;
  assignment?: string;
  synthetic?: boolean;
}

export interface RedeemResult {
  redemption_id: number;
  replayed: boolean;
  applied: boolean;
  offer_code?: string;
  campaign_id?: number;
  units: number;
  gross_value_aed?: string;
  discount_aed: string;
  net_value_aed: string;
  margin_aed?: string;
  stock_remaining?: number;
  detail?: string;
  guardrails?: { auto_paused: boolean; breaches: GuardrailBreach[] };
}

export interface GuardrailBreach {
  breach: string;
  severity: string;
  detail: string;
  skus?: Array<{ store_id: number; item_id: number; on_hand: number; reorder_point: number }>;
}

export interface DecisionTrace {
  decision: {
    id: number; campaign_id: number | null; customer_id: number;
    customer_name: string | null; store_id: number | null; store_name: string | null;
    item_id: number | null; item_name: string | null; category: string | null;
    action_type: ActionType; decided_at: string;
  };
  model_inputs: {
    churn_probability: number; uplift: number; redemption_probability: number;
    churn_model: string | null; algorithm: string | null;
  };
  price_snapshot: { unit_price_aed: string; unit_cost_aed: string; discount_pct: string; note: string };
  eiv_breakdown: Record<string, string>;
  reason_codes: string[];
  rejected_actions: RejectedAction[];
  inventory_snapshot: AtpSnapshot | Record<string, never>;
  budget_snapshot: Partial<BudgetSnapshot>;
  policy_version: string;
  reproducibility: {
    recomputed_eiv_aed: string; recorded_eiv_aed: string;
    matches: boolean; delta_aed: string; policy_version: string;
  };
}

export interface LiveMetrics {
  campaign_id: number;
  status: CampaignStatus;
  pause_reason: string | null;
  period: { from: string; to: string };
  audience: Record<string, number>;
  offers: Record<string, number>;
  redemptions: {
    count: number; units: number;
    discount_aed: string; net_value_aed: string; margin_aed: string;
  };
  budget: BudgetExposure & { burn_pct: number };
  guardrails: { breaches: GuardrailBreach[]; hard_breaches: number };
}

export interface MeasurementResult {
  campaign_id: number;
  campaign_name: string;
  measured_window: { from: string; to: string; days: number };
  treatment: { size: number; retained: number; retention_rate: number };
  control: { size: number; retained: number; retention_rate: number };
  incremental_retention: number;
  incremental_customers_retained: number;
  gross_revenue_aed: string;
  incremental_revenue_aed: string;
  incremental_margin_aed: string;
  discount_spend_aed: string;
  procurement_cost_aed: string;
  cost_per_retained_aed: string | null;
  campaign_roi: string | null;
  budget_variance_aed: string;
  stockout_rate: number;
  redemptions: number;
  uplift_by_segment: Record<string, {
    treatment?: { size: number; retained: number; rate: number };
    control?: { size: number; retained: number; rate: number };
    incremental_retention: number;
    reliable: boolean;
    note?: string;
  }>;
  causal_note: string;
  validity: string[];
  synthetic: boolean;
}

export interface FlywheelCustomer {
  id: number;
  external_ref: string;
  display_name: string;
  store_id: number;
  store_name: string;
  loyalty_tier: string;
  status: string;
  archetype: string;
  churn_probability: number | null;
  risk_band: RiskBand | null;
  reason_codes: Array<{ code: string; detail: string; impact: number }>;
}

export interface CustomerDetail {
  customer: {
    id: number; display_name: string; external_ref: string;
    store_id: number; store_name: string; loyalty_tier: string;
    status: string; archetype: string; enrolled_on: string;
  };
  churn: {
    churn_probability: number; risk_band: RiskBand;
    reason_codes: Array<{ code: string; detail: string; impact: number }>;
    as_of: string; model_version: string; algorithm: string;
  } | null;
  features: Record<string, number>;
  events: Array<{ type: string; at: string; item_id: number | null; category: string | null; units: number; value_aed: string }>;
  consents: Array<{ channel: string; granted: boolean; max_per_week: number }>;
  contact_status: { contacts_last_7_days: number };
  offers: Array<{ offer_code: string; action: string; discount_pct: string; status: string; issued_at: string; expires_at: string }>;
  synthetic: boolean;
}

export interface ModelVersion {
  id: number;
  kind: string;
  algorithm: string;
  version: string;
  metrics: Record<string, number>;
  is_active: boolean;
  trained_at: string | null;
  feature_window_days: number;
  outcome_window_days: number;
  random_seed: number;
  notes: string | null;
}

export interface FlywheelHealth {
  customers: number;
  campaigns: number;
  decisions: number;
  redemptions: number;
  latest_feature_snapshot: string | null;
  outbox_pending: number;
  outbox_healthy: boolean;
  synthetic: boolean;
}

// ── Horizon 1: proving it ──────────────────────────────────────────────────

/** How a readout should be presented. `not_measurable` and `inconclusive` are
 *  NORMAL states, not errors — styling them as failures trains users to stop
 *  campaigns early, which is exactly what the confidence sequence exists to
 *  make unnecessary. */
export type ReadoutState =
  | 'not_measurable' | 'inconclusive' | 'significant_but_small' | 'significant';

export interface Interpretation {
  state: ReadoutState;
  headline: string;
  detail: string;
  actionable: boolean;
}

export interface ReadoutPoint {
  window_start: string;
  window_end: string;
  treatment_n: number;
  control_n: number;
  treatment_converted: number;
  control_converted: number;
  incremental_retention: number;
  /** Anytime-valid bounds. Null when the arms are too small to say anything. */
  ci_lower: number | null;
  ci_upper: number | null;
  log_e_value: number | null;
  is_significant: boolean;
  meets_mde: boolean;
  incremental_margin_aed: string;
  total_cost_aed: string;
  margin_per_aed_spent: string | null;
  validity_warnings: string[];
  computed_at: string | null;
}

export interface Preregistration {
  id: number;
  primary_metric: string;
  window_days: number;
  stopping_rule: string;
  alpha: number;
  min_detectable_effect: number;
  planned_treatment_n: number;
  planned_control_n: number;
  control_pct: string;
  registered_at: string | null;
  notes: string | null;
}

export interface CampaignReadout {
  campaign_id: number;
  state: 'measured' | 'not_yet_measured';
  readout: ReadoutPoint | null;
  interpretation?: Interpretation;
  preregistration?: Preregistration | null;
  note?: string;
}

export interface IncrementalitySummary {
  campaigns_measured: number;
  significant: number;
  proven_positive: number;
  proven_negative: number;
  inconclusive: number;
  incremental_margin_aed: string;
  total_spend_aed: string;
  margin_per_aed_spent: string | null;
  note: string;
}

export interface BalanceCheckRow {
  covariate: string;
  treatment_mean: number;
  control_mean: number;
  pooled_sd: number;
  smd: number;
  threshold: number;
  is_balanced: boolean;
}

export interface BalanceSummary {
  status: 'balanced' | 'imbalanced' | 'unknown';
  checked: number;
  imbalanced: string[];
  note: string;
}

export interface CampaignHoldout {
  campaign_id: number;
  arms: { treatment: number; control: number };
  balance: { checks: BalanceCheckRow[]; summary: BalanceSummary };
  assignment_method: string;
}

export interface HoldoutOverviewRow {
  campaign_id: number;
  name: string;
  status: string;
  treatment_n: number;
  control_n: number;
  control_share: number;
  adequate: boolean;
}

export interface HoldoutOverview {
  campaigns: HoldoutOverviewRow[];
  note: string;
}

export interface ContactPolicyRow {
  channel: string;
  max_per_week: number;
  max_per_day: number;
  cooldown_days_after_ignores: number;
  ignores_before_cooldown: number;
  is_active: boolean;
  volume: { last_24h: number; last_7d: number; distinct_customers_7d: number };
}

export interface GovernanceOverview {
  policies: ContactPolicyRow[];
  fatigue: { customer_id: number; contacts_7d: number; last_contact: string | null }[];
  suppressions_by_reason: Record<string, number>;
  suppressed_30d: number;
  recent_suppressions: {
    customer_id: number;
    suppressed_campaign_id: number | null;
    winning_campaign_id: number | null;
    reason_code: string;
    detail: string | null;
    created_at: string | null;
    suppressed_campaign_name: string | null;
    winning_campaign_name: string | null;
  }[];
  interpretation: string;
}

export interface ShadowComparisonRow {
  model_label: string;
  scored: number;
  disagreements: number;
  disagreement_rate: number;
  /** True when the "model" IS the rule tier — 0% disagreement is then an
   *  identity, not a result. The UI must say so. */
  is_self_comparison: boolean;
  self_comparison_warning: string | null;
  by_kind: { action: number; magnitude: number; both: number };
  rule_eiv_aed: string;
  shadow_eiv_aed: string;
  claimed_eiv_delta_aed: string;
  claimed_delta_note: string;
}

export interface PromotionStanding {
  model_label: string;
  status: string;
  readouts_passed: number;
  readouts_required: number;
  min_ci_lower: number;
  disagreement_rate: number | null;
  max_disagreement_rate: number;
  scored: number;
  eligible_for_promotion: boolean;
  blockers: string[];
  blocked_reason: string | null;
  updated_at: string | null;
}

export interface ShadowOverview {
  comparison: ShadowComparisonRow[];
  promotion: PromotionStanding[];
  governing_rule: string;
}

export interface AllocationRun {
  id: number;
  mode: 'greedy' | 'portfolio';
  is_shadow: boolean;
  budget_limit_aed: string;
  customers_considered: number;
  candidates_considered: number;
  actions_selected: number;
  total_eiv_aed: string;
  total_cost_aed: string;
  binding_constraint: string | null;
  eiv_delta_vs_greedy_aed: string | null;
  solver: string;
  runtime_ms: number | null;
  created_at: string | null;
}

// ── Horizon 3: two tracks ───────────────────────────────────────────────────

export interface TradeFunding {
  funding_id: number;
  supplier_id: number;
  supplier_name: string;
  campaign_id: number;
  campaign_name: string;
  funding_type: 'co_op' | 'scan_down' | 'fixed_fee';
  status: string;
  committed_aed: string;
  spent_aed: string;
  settled_aed: string;
}

export interface TradeOverview {
  fundings: TradeFunding[];
  note: string;
}

export interface Settlement {
  settlement_id: number;
  period: { from: string; to: string };
  amount_due_aed: string;
  status: string;
  incremental_units: number;
  incremental_margin_aed: string;
}

export interface SupplierFundingRow {
  funding_id: number;
  campaign_id: number;
  campaign_name: string;
  funding_type: string;
  status: string;
  committed_aed: string;
  spent_aed: string;
  settled_aed: string;
  starts_on: string | null;
  ends_on: string | null;
  settlements: Settlement[];
}

export interface SupplierDashboard {
  supplier_id: number;
  funded_sku_count: number;
  totals: { committed_aed: string; settled_aed: string };
  fundings: SupplierFundingRow[];
  confidentiality_note: string;
}

export interface CannibalizationRow {
  category: string;
  promoted_item_id: number | null;
  promoted_lift_units: number;
  category_net_lift_units: number;
  cannibalized_units: number;
  cannibalization_rate: number | null;
  net_incremental_margin_aed: string;
  is_reliable: boolean;
  note: string;
  window_end: string;
}

export interface CannibalizationResult {
  campaign_id: number;
  results: CannibalizationRow[];
}

export interface MeteringSummary {
  period: { from: string; to: string };
  usage: { decisions_served: number; customers_scored: number };
  included: { decisions: number; customers_scored: number };
  billable: { decisions: number; customers_scored: number };
  charges_aed: {
    platform_fee: string;
    metered_decisions: string;
    metered_scoring: string;
    total: string;
  };
  pricing: Record<string, unknown>;
  note: string;
}

// ── Horizon 4: expand ────────────────────────────────────────────────────────

export interface SeasonEntry {
  id: number;
  name: string;
  kind: string;
  starts_on: string;
  ends_on: string;
  demand_multiplier: string;
  category: string | null;
  note: string | null;
  active: boolean;
}

export interface SeasonalityCalendar {
  calendar: SeasonEntry[];
  active_now: SeasonEntry[];
  current_factor: string;
  note: string;
}

export interface ShelfLifeCandidate {
  batch_id: number;
  store_id: number;
  store_name: string;
  item_id: number;
  item_name: string;
  category: string;
  batch_ref: string;
  units: number;
  expires_on: string;
  days_to_expiry: number;
  urgency: number;
  value_at_risk_aed: string;
  recommended_markdown_pct: string;
  recommendation: string;
}

export interface ShelfLifeResult {
  candidates: ShelfLifeCandidate[];
  count: number;
  total_value_at_risk_aed: string;
  note: string;
}

export interface CoalitionPartnerRow {
  partner_name: string;
  partner_type: string;
  customers: number;
  attributed_margin_aed: string;
  avg_weight: number | null;
}

export interface CoalitionAttribution {
  campaign_id: number;
  by_partner: CoalitionPartnerRow[];
}

export interface OutcomePlan {
  plan_id: number;
  plan_name: string;
  margin_share_pct: string;
  gate_readouts_required: number;
  gate_met: boolean;
  chargeable: boolean;
  status: string;
  gate_evidence: Record<string, unknown>;
}

export interface OutcomePricingStatus {
  plans: OutcomePlan[];
  note: string;
}
