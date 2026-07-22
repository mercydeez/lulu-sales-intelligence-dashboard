'use client';

/**
 * Campaign Studio — the multi-step journey (§20.1).
 *
 * Objective → Audience → Offer policy → Inventory & fulfilment →
 * Financial simulation → Approval path → Review & launch.
 *
 * WHY A WIZARD RATHER THAN ONE FORM. Each step depends on the previous one
 * having actually run on the server: the audience cannot be built before the
 * campaign exists, the simulation cannot run before the audience does, and the
 * approval chain is sized from the simulation's numbers. The steps are the real
 * dependency order, not a cosmetic split.
 *
 * Progress is forward-only by design once the server has acted — going "back"
 * to change the discount cap after a simulation would leave the displayed
 * numbers describing a campaign that no longer exists. Editing is done by
 * re-running the affected step, which re-simulates.
 */
import { useCallback, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion, useReducedMotion } from 'framer-motion';
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, Loader2, PackageSearch,
  Rocket, Sparkles, Target, TrendingUp, Users, Wallet,
} from 'lucide-react';
import { Badge, Button, Card, Input, PageHeader, Select } from '@/components/ui';
import { EASE, Reveal, SyntheticBadge } from '@/components/flywheel/motion';
import {
  LADDER_LABELS, aed, buildAudience, createCampaign, fetchCampaignDataTrust,
  simulateCampaign, submitCampaign,
} from '@/lib/flywheel';
import { DataTrustPanel } from '@/components/flywheel/DataTrustPanel';
import type { AudienceResult, DataTrustReport, SimulationResult } from '@/types/flywheel';

const STEPS = [
  { key: 'objective', label: 'Objective', icon: Target },
  { key: 'audience', label: 'Audience', icon: Users },
  { key: 'offer', label: 'Offer policy', icon: Sparkles },
  { key: 'inventory', label: 'Stock & fulfilment', icon: PackageSearch },
  { key: 'simulation', label: 'Financial simulation', icon: TrendingUp },
  { key: 'approval', label: 'Approval path', icon: Wallet },
  { key: 'launch', label: 'Review & launch', icon: Rocket },
] as const;

const today = new Date();
const isoDate = (d: Date) => d.toISOString().slice(0, 10);

export default function CampaignStudio() {
  const router = useRouter();
  const reduce = useReducedMotion();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    name: '',
    objective: 'retain_at_risk',
    starts_on: isoDate(today),
    ends_on: isoDate(new Date(today.getTime() + 30 * 864e5)),
    channel: 'email',
    max_discount_pct: 20,
    min_margin_pct: 10,
    discount_budget_aed: 25000,
    procurement_budget_aed: 0,
    safety_stock_pct: 10,
    control_group_pct: 20,
    contact_cap_per_week: 2,
    min_churn_probability: 0.3,
    max_size: 2000,
  });

  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [audience, setAudience] = useState<AudienceResult | null>(null);
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [approval, setApproval] = useState<{ request_id: number; step_count: number } | null>(null);
  const [trust, setTrust] = useState<DataTrustReport | null>(null);
  const [trustLoading, setTrustLoading] = useState(false);
  const [trustUnavailable, setTrustUnavailable] = useState<string | null>(null);

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const guard = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await fn(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Something went wrong'); }
    finally { setBusy(false); }
  }, []);

  const createDraft = () => guard(async () => {
    if (form.name.trim().length < 3) throw new Error('Give the campaign a name of at least 3 characters');
    if (form.ends_on < form.starts_on) throw new Error('The end date must be on or after the start date');
    const created = await createCampaign({
      name: form.name, objective: form.objective,
      starts_on: form.starts_on, ends_on: form.ends_on, channel: form.channel,
      max_discount_pct: form.max_discount_pct, min_margin_pct: form.min_margin_pct,
      discount_budget_aed: form.discount_budget_aed,
      procurement_budget_aed: form.procurement_budget_aed,
      safety_stock_pct: form.safety_stock_pct,
      control_group_pct: form.control_group_pct,
      contact_cap_per_week: form.contact_cap_per_week,
      audience_spec: {},
    });
    setCampaignId(created.campaign_id);
    setStep(1);
  });

  const runAudience = () => guard(async () => {
    if (!campaignId) throw new Error('Create the campaign first');
    const result = await buildAudience(campaignId, {
      min_churn_probability: form.min_churn_probability, max_size: form.max_size,
    });
    if (result.total === 0) {
      throw new Error('No customers matched. Lower the churn floor, or seed customers from the Flywheel home page.');
    }
    setAudience(result);
    setStep(2);
  });

  // The verdict is fetched when the operator ARRIVES at the simulation step, not
  // when they press the button. The server refuses to simulate on NOT_READY, and
  // discovering that only after pressing turns spent effort into a dead end; this
  // way the reasons are on screen while there is still something to do about them.
  //
  // A failure here never blocks the wizard — an unreachable checker is not
  // evidence that the data is bad, and the server enforces the gate regardless.
  const loadTrust = useCallback(async (id: number) => {
    setTrustLoading(true); setTrustUnavailable(null);
    try {
      setTrust(await fetchCampaignDataTrust(id));
    } catch (e) {
      setTrust(null);
      setTrustUnavailable(e instanceof Error ? e.message : 'check failed');
    } finally {
      setTrustLoading(false);
    }
  }, []);

  const goToSimulation = () => guard(async () => {
    if (!campaignId) throw new Error('Create the campaign first');
    setStep(4);
    await loadTrust(campaignId);
  });

  const runSimulation = () => guard(async () => {
    if (!campaignId) throw new Error('Create the campaign first');
    try {
      const result = await simulateCampaign(campaignId, 400);
      setSimulation(result);
      // The response carries its own verdict; prefer it over the pre-flight copy.
      if (result.data_trust) setTrust(result.data_trust);
      setStep(4);
    } catch (e) {
      // A refusal is the gate doing its job. Re-read the report so the panel
      // shows WHICH inputs are at fault rather than just the refusal text.
      await loadTrust(campaignId);
      throw e;
    }
  });

  const runSubmit = () => guard(async () => {
    if (!campaignId) throw new Error('Create the campaign first');
    const result = await submitCampaign(campaignId);
    setApproval({ request_id: result.request_id, step_count: result.step_count });
    setSimulation(result.simulation);
    setStep(6);
  });

  const canAdvance = useMemo(() => {
    switch (step) {
      case 0: return form.name.trim().length >= 3;
      case 1: return !!audience;
      case 2: return true;
      case 3: return true;
      case 4: return !!simulation;
      case 5: return !!approval;
      default: return true;
    }
  }, [step, form.name, audience, simulation, approval]);

  const expected = simulation?.scenarios.expected;
  const shortages = simulation?.inventory.shortages ?? [];
  const resolutions = simulation?.inventory.resolutions ?? [];

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <PageHeader
        eyebrow="Flywheel"
        title="Campaign Studio"
        description="Build a retention campaign the loop can actually execute — audience, offer policy, stock, money, approval."
        icon={<Sparkles className="w-5 h-5" />}
        actions={<SyntheticBadge />}
      />

      {/* Stepper — real <ol> so it reads as a sequence to assistive tech. */}
      <nav aria-label="Campaign steps" className="mb-6 overflow-x-auto">
        <ol className="flex min-w-max items-center gap-1">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            const state = i < step ? 'done' : i === step ? 'current' : 'todo';
            return (
              <li key={s.key} className="flex items-center">
                <div
                  className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                    state === 'current'
                      ? 'bg-teal-700 text-white'
                      : state === 'done'
                        ? 'bg-teal-50 text-teal-800 dark:bg-teal-500/10 dark:text-teal-300'
                        : 'text-ink-muted'
                  }`}
                  aria-current={state === 'current' ? 'step' : undefined}
                >
                  {state === 'done' ? <Check className="w-3.5 h-3.5" /> : <Icon className="w-3.5 h-3.5" />}
                  <span className="whitespace-nowrap">{s.label}</span>
                </div>
                {i < STEPS.length - 1 && (
                  <span aria-hidden className={`mx-1 h-px w-4 ${i < step ? 'bg-teal-400' : 'bg-surface-3'}`} />
                )}
              </li>
            );
          })}
        </ol>
      </nav>

      {error && (
        <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/*
        NO AnimatePresence, NO exit animation, NO opacity fade — deliberately.

        This used to be <AnimatePresence mode="wait"> with an exit animation.
        `mode="wait"` will not MOUNT the incoming child until the outgoing child's
        exit animation reports completion, and framer-motion drives animations
        with requestAnimationFrame. rAF is suspended whenever the document is
        hidden — a background tab, an embedded webview, a headless/automation
        context — so the exit never completed, the next panel never mounted, and
        the wizard froze on whichever step it was on while `step` advanced
        invisibly underneath it (the footer button, which sits outside this
        wrapper, kept updating, which is what made it look so baffling).

        Measured in an embedded preview: visibilityState 'hidden',
        0 rAF frames in 500ms, and no step panel in the DOM at all.

        Dropping `mode="wait"` alone is not enough: AnimatePresence would then
        keep the OUTGOING panel mounted until its exit completed, stacking two
        steps on top of each other in the same conditions. So the exit goes too,
        and the changing `key` lets React swap panels synchronously.

        The enter animation is TRANSFORM-ONLY on purpose. An opacity fade starting
        at 0 has the same failure shape — with no rAF the panel mounts and stays
        invisible, which is the "cards invisible (opacity 0)" bug this repo has
        already fixed once. A transform that never animates leaves the content
        12px off-target and perfectly readable.

        motion.tsx states the rule this restores: motion is never load-bearing
        for meaning.
      */}
        <motion.div
          key={step}
          initial={reduce ? false : { x: 12 }}
          animate={{ x: 0 }}
          transition={{ duration: reduce ? 0 : 0.28, ease: EASE }}
        >
          {/* ── 0. Objective ─────────────────────────────────────────── */}
          {step === 0 && (
            <Card padding="lg">
              <h2 className="text-base font-semibold text-ink">What is this campaign for?</h2>
              <p className="mt-1 text-sm text-ink-muted">
                The objective shapes which customers are eligible and which actions the optimizer will consider.
              </p>
              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <label className="block sm:col-span-2">
                  <span className="text-xs font-medium text-ink-soft">Campaign name</span>
                  <Input value={form.name} onChange={(e) => set('name', e.target.value)}
                         placeholder="Q3 win-back — Dubai declining shoppers" className="mt-1" />
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Objective</span>
                  <Select value={form.objective} onChange={(e) => set('objective', e.target.value)} className="mt-1">
                    <option value="retain_at_risk">Retain at-risk customers</option>
                    <option value="reactivate_lapsed">Reactivate lapsed customers</option>
                    <option value="grow_basket">Grow basket size</option>
                    <option value="protect_margin">Protect margin</option>
                  </Select>
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Channel</span>
                  <Select value={form.channel} onChange={(e) => set('channel', e.target.value)} className="mt-1">
                    <option value="email">Email</option>
                    <option value="sms">SMS</option>
                    <option value="push">Push</option>
                    <option value="app">In-app</option>
                    <option value="in_store">In store</option>
                  </Select>
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Starts on</span>
                  <Input type="date" value={form.starts_on}
                         onChange={(e) => set('starts_on', e.target.value)} className="mt-1" />
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Ends on</span>
                  <Input type="date" value={form.ends_on}
                         onChange={(e) => set('ends_on', e.target.value)} className="mt-1" />
                </label>
              </div>
            </Card>
          )}

          {/* ── 1. Audience ──────────────────────────────────────────── */}
          {step === 1 && (
            <Card padding="lg">
              <h2 className="text-base font-semibold text-ink">Who should this reach?</h2>
              <p className="mt-1 text-sm text-ink-muted">
                Eligibility is churn risk plus consent plus store scope. A share is held back as a
                control group so the campaign's true lift is measurable rather than assumed.
              </p>
              <div className="mt-5 grid gap-4 sm:grid-cols-3">
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">
                    Minimum churn risk
                  </span>
                  <Input type="number" step="0.05" min="0" max="0.95"
                         value={form.min_churn_probability}
                         onChange={(e) => set('min_churn_probability', Number(e.target.value))}
                         className="mt-1" />
                  <span className="mt-1 block text-[11px] text-ink-muted">
                    Below this, an intervention rarely pays for itself.
                  </span>
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Maximum audience</span>
                  <Input type="number" min="10" max="5000" value={form.max_size}
                         onChange={(e) => set('max_size', Number(e.target.value))} className="mt-1" />
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">
                    Control group %
                  </span>
                  <Input type="number" min="0" max="50" value={form.control_group_pct}
                         onChange={(e) => set('control_group_pct', Number(e.target.value))} className="mt-1" />
                  <span className="mt-1 block text-[11px] text-ink-muted">
                    Held back entirely — no offers, still measured.
                  </span>
                </label>
              </div>

              {audience && (
                <Reveal>
                  <div className="mt-5 grid gap-3 sm:grid-cols-3 rounded-lg bg-surface-2 p-4">
                    <div>
                      <p className="font-mono text-2xl text-ink">
                        {audience.treatment.toLocaleString()}
                      </p>
                      <p className="text-xs text-ink-muted">will receive offers</p>
                    </div>
                    <div>
                      <p className="font-mono text-2xl text-ink">
                        {audience.control.toLocaleString()}
                      </p>
                      <p className="text-xs text-ink-muted">
                        control ({audience.control_pct_actual}% actual)
                      </p>
                    </div>
                    <div>
                      <p className="font-mono text-2xl text-ink">
                        {audience.total.toLocaleString()}
                      </p>
                      <p className="text-xs text-ink-muted">total eligible</p>
                    </div>
                  </div>
                </Reveal>
              )}
            </Card>
          )}

          {/* ── 2. Offer policy ──────────────────────────────────────── */}
          {step === 2 && (
            <Card padding="lg">
              <h2 className="text-base font-semibold text-ink">Offer policy</h2>
              <p className="mt-1 text-sm text-ink-muted">
                Hard bounds the optimizer may never cross. It will choose the cheapest action that
                still wins — a high churn score alone never buys a discount.
              </p>
              <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Max discount %</span>
                  <Input type="number" min="0" max="90" value={form.max_discount_pct}
                         onChange={(e) => set('max_discount_pct', Number(e.target.value))} className="mt-1" />
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Min margin %</span>
                  <Input type="number" min="0" max="100" value={form.min_margin_pct}
                         onChange={(e) => set('min_margin_pct', Number(e.target.value))} className="mt-1" />
                  <span className="mt-1 block text-[11px] text-ink-muted">Floor after discount.</span>
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Discount budget (AED)</span>
                  <Input type="number" min="0" value={form.discount_budget_aed}
                         onChange={(e) => set('discount_budget_aed', Number(e.target.value))} className="mt-1" />
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Contacts / week</span>
                  <Input type="number" min="0" max="14" value={form.contact_cap_per_week}
                         onChange={(e) => set('contact_cap_per_week', Number(e.target.value))} className="mt-1" />
                </label>
              </div>
            </Card>
          )}

          {/* ── 3. Inventory ─────────────────────────────────────────── */}
          {step === 3 && (
            <Card padding="lg">
              <h2 className="text-base font-semibold text-ink">Stock & fulfilment</h2>
              <p className="mt-1 text-sm text-ink-muted">
                Offers are gated on available-to-promise. When stock is short, Flywheel walks a fixed
                ladder — cheapest resolution first — rather than silently overselling.
              </p>
              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">Safety stock %</span>
                  <Input type="number" min="0" max="100" value={form.safety_stock_pct}
                         onChange={(e) => set('safety_stock_pct', Number(e.target.value))} className="mt-1" />
                  <span className="mt-1 block text-[11px] text-ink-muted">
                    Never lowers a store's existing reorder point — only raises the floor.
                  </span>
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-ink-soft">
                    Procurement budget (AED)
                  </span>
                  <Input type="number" min="0" value={form.procurement_budget_aed}
                         onChange={(e) => set('procurement_budget_aed', Number(e.target.value))} className="mt-1" />
                  <span className="mt-1 block text-[11px] text-ink-muted">
                    0 disables buying stock to fund this campaign.
                  </span>
                </label>
              </div>
              <ol className="mt-5 flex flex-wrap gap-2 text-[11px]">
                {Object.entries(LADDER_LABELS).filter(([k]) => k !== 'none').map(([key, label], i) => (
                  <li key={key} className="flex items-center gap-2">
                    <span className="rounded-full bg-surface-2 px-2.5 py-1 text-ink-soft">
                      {i + 1}. {label}
                    </span>
                    {i < 5 && <span aria-hidden className="text-ink-muted">→</span>}
                  </li>
                ))}
              </ol>
            </Card>
          )}

          {/* ── 4. Simulation ────────────────────────────────────────── */}
          {step === 4 && (
            <Card padding="lg">
              <h2 className="text-base font-semibold text-ink">Financial simulation</h2>

              {/* Readiness first: it decides whether the button below will work
                  at all, so it belongs above the button, not beside the results. */}
              <DataTrustPanel
                report={trust}
                loading={trustLoading}
                unavailable={trustUnavailable}
                className="mt-3"
              />

              {!simulation ? (
                <p className="mt-3 text-sm text-ink-muted">
                  Run the real optimizer over a sample of the audience to see what this campaign
                  would actually do. Nothing is committed.
                </p>
              ) : (
                <>
                  <p className="mt-1 text-sm text-ink-muted">
                    {simulation.audience.note}
                  </p>

                  <div className="mt-5 grid gap-3 sm:grid-cols-3">
                    {(['pessimistic', 'expected', 'optimistic'] as const).map((key) => {
                      const s = simulation.scenarios[key];
                      const isExpected = key === 'expected';
                      return (
                        <div key={key}
                             className={`rounded-lg border p-4 ${isExpected
                               ? 'border-teal-300 bg-teal-50/50 dark:border-teal-600 dark:bg-teal-500/5'
                               : 'border-line'}`}>
                          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                            {key}
                          </p>
                          <p className="mt-2 font-mono text-xl text-ink">
                            {aed(s.net_value_aed)}
                          </p>
                          <p className="text-xs text-ink-muted">net value (AED)</p>
                          <dl className="mt-3 space-y-1 text-[11px]">
                            <div className="flex justify-between">
                              <dt className="text-ink-muted">Discount spend</dt>
                              <dd className="font-mono text-amber-700 dark:text-amber-400">{aed(s.discount_spend_aed)}</dd>
                            </div>
                            <div className="flex justify-between">
                              <dt className="text-ink-muted">Incremental margin</dt>
                              <dd className="font-mono text-ink-soft">{aed(s.incremental_margin_aed)}</dd>
                            </div>
                            <div className="flex justify-between">
                              <dt className="text-ink-muted">ROI</dt>
                              <dd className="font-mono font-semibold text-teal-700 dark:text-teal-300">{s.roi}×</dd>
                            </div>
                          </dl>
                        </div>
                      );
                    })}
                  </div>

                  {simulation.uncertainty && (() => {
                    const u = simulation.uncertainty!;
                    const lossPct = u.loss_probability * 100;
                    const lossTone = lossPct > 20
                      ? 'text-rose-700 dark:text-rose-400'
                      : lossPct > 5
                        ? 'text-amber-700 dark:text-amber-400'
                        : 'text-teal-700 dark:text-teal-300';
                    const cvarNegative = Number(u.cvar_5pct_aed) < 0;
                    return (
                      <div className="mt-5 rounded-lg border border-line p-4">
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <h3 className="text-sm font-semibold text-ink">
                            Uncertainty
                          </h3>
                          <p className="text-[11px] text-ink-muted">
                            {u.trials.toLocaleString()} simulations · response CV {u.response_cv}
                          </p>
                        </div>
                        <p className="mt-1 text-xs text-ink-muted">
                          The three cards above vary redemption by fixed 0.6×/1.0×/1.4× factors.
                          These figures sample a lognormal response multiplier instead, so they
                          carry a tail and a probability of loss.
                        </p>

                        {/* distribution */}
                        <div className="mt-4 grid gap-3 sm:grid-cols-3">
                          {([
                            ['P10 — downside', u.net_value_p10_aed],
                            ['P50 — median', u.net_value_p50_aed],
                            ['P90 — upside', u.net_value_p90_aed],
                          ] as const).map(([label, value]) => (
                            <div key={label}>
                              <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
                                {label}
                              </p>
                              <p className="mt-1 font-mono text-lg text-ink">
                                {aed(value)}
                              </p>
                            </div>
                          ))}
                        </div>

                        {/* tail + risk */}
                        <dl className="mt-4 grid gap-3 border-t border-line pt-3 text-xs sm:grid-cols-4">
                          <div>
                            <dt className="text-ink-muted">CVaR 5% (tail loss)</dt>
                            <dd className={`mt-0.5 font-mono font-semibold ${
                              cvarNegative ? 'text-rose-700 dark:text-rose-400'
                                           : 'text-ink-soft'}`}>
                              {aed(u.cvar_5pct_aed)}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-ink-muted">Probability of loss</dt>
                            <dd className={`mt-0.5 font-mono font-semibold ${lossTone}`}>
                              {lossPct.toFixed(1)}%
                            </dd>
                          </div>
                          <div>
                            <dt className="text-ink-muted">Mean net value</dt>
                            <dd className="mt-0.5 font-mono text-ink-soft">
                              {aed(u.net_value_mean_aed)}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-ink-muted">Mean ROI</dt>
                            <dd className="mt-0.5 font-mono font-semibold text-teal-700 dark:text-teal-300">
                              {u.roi_mean}×
                            </dd>
                          </div>
                        </dl>

                        <p className="mt-3 text-[11px] text-ink-muted">
                          CVaR is the mean of the worst 5% of outcomes, not a percentile — it is
                          what a bad run actually costs. Seeded from the campaign, so this
                          simulation reproduces exactly.
                        </p>
                      </div>
                    );
                  })()}

                  {!simulation.budget_sufficient && (
                    <div role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
                      <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                      <span>
                        Expected discount spend of {aed(expected?.discount_spend_aed)} AED exceeds the
                        declared budget of {aed(simulation.discount_budget_declared_aed)} AED.
                        Raise the budget or tighten the offer policy before submitting.
                      </span>
                    </div>
                  )}

                  <div className="mt-5">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                      Action mix across the sample
                    </h3>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {Object.entries(simulation.action_mix).map(([action, count]) => (
                        <Badge key={action} variant={action === 'NO_ACTION' ? 'neutral' : 'teal'}>
                          {action.replace(/_/g, ' ').toLowerCase()} · {count}
                        </Badge>
                      ))}
                    </div>
                  </div>

                  {shortages.length > 0 && (
                    <div className="mt-5">
                      <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                        Stock shortages & how Flywheel would resolve them
                      </h3>
                      <ul className="mt-2 space-y-2">
                        {resolutions.map((r, i) => (
                          <li key={`${r.store_id}-${r.item_id}-${i}`}
                              className="rounded-lg border border-line p-3 text-xs">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge variant={r.rung === 'e_procurement' ? 'amber' : 'teal'}>
                                {LADDER_LABELS[r.rung] ?? r.rung}
                              </Badge>
                              <span className="text-ink-muted">
                                store {r.store_id} · item {r.item_id}
                              </span>
                            </div>
                            <p className="mt-1.5 text-ink-soft">{r.detail}</p>
                            {r.procurement_rejected && (
                              <p className="mt-1 text-amber-700 dark:text-amber-400">
                                Procurement refused: {r.procurement_rejected.detail}
                              </p>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </Card>
          )}

          {/* ── 5. Approval path ─────────────────────────────────────── */}
          {step === 5 && (
            <Card padding="lg">
              <h2 className="text-base font-semibold text-ink">Approval path</h2>
              <p className="mt-1 text-sm text-ink-muted">
                The chain is sized from this campaign's actual exposure — bigger spend pulls in more
                approvers. Steps at the same stage run in parallel.
              </p>
              <div className="mt-5 rounded-lg bg-surface-2 p-4">
                <dl className="grid gap-3 sm:grid-cols-2 text-sm">
                  <div>
                    <dt className="text-xs text-ink-muted">Discount exposure</dt>
                    <dd className="font-mono text-lg text-ink">
                      {aed(expected?.discount_spend_aed)} AED
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-muted">Expected ROI</dt>
                    <dd className="font-mono text-lg text-teal-700 dark:text-teal-300">
                      {expected?.roi ?? '—'}×
                    </dd>
                  </div>
                </dl>
              </div>
              <p className="mt-4 text-xs text-ink-muted">
                Submitting re-runs the simulation first, so approvers always judge current numbers —
                never a stale estimate from an earlier session.
              </p>
            </Card>
          )}

          {/* ── 6. Launched ──────────────────────────────────────────── */}
          {step === 6 && approval && campaignId && (
            <Card padding="lg">
              <div className="flex items-start gap-3">
                <div className="rounded-full bg-teal-100 p-2 dark:bg-teal-500/15">
                  <Check className="w-5 h-5 text-teal-700 dark:text-teal-300" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-ink">
                    Submitted for approval
                  </h2>
                  <p className="mt-1 text-sm text-ink-muted">
                    {approval.step_count} approval step(s) opened. The campaign cannot issue a single
                    offer, reserve a dirham, or touch stock until every step is approved.
                  </p>
                </div>
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => router.push('/flywheel/approvals')}>
                  Open approval inbox <ArrowRight className="w-4 h-4 ms-1.5" />
                </Button>
                <Button variant="secondary" onClick={() => router.push(`/flywheel/campaigns/${campaignId}`)}>
                  View campaign
                </Button>
              </div>
            </Card>
          )}
        </motion.div>

      {/* Navigation */}
      {step < 6 && (
        <div className="mt-6 flex items-center justify-between gap-3">
          <Button
            variant="ghost"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0 || busy}
          >
            <ArrowLeft className="w-4 h-4 me-1.5" />Back
          </Button>

          <div className="flex items-center gap-2">
            {step === 0 && (
              <Button variant="primary" onClick={createDraft} disabled={busy || !canAdvance}>
                {busy ? <Loader2 className="w-4 h-4 me-1.5 animate-spin" /> : null}
                Create draft
              </Button>
            )}
            {step === 1 && (
              <Button variant="primary" onClick={runAudience} disabled={busy}>
                {busy ? <Loader2 className="w-4 h-4 me-1.5 animate-spin" /> : <Users className="w-4 h-4 me-1.5" />}
                Build audience
              </Button>
            )}
            {step === 2 && (
              <Button variant="primary" onClick={() => setStep((s) => s + 1)} disabled={busy}>
                Continue <ArrowRight className="w-4 h-4 ms-1.5" />
              </Button>
            )}
            {/* Entering the simulation step pre-flights the data-trust check. */}
            {step === 3 && (
              <Button variant="primary" onClick={goToSimulation} disabled={busy}>
                Continue <ArrowRight className="w-4 h-4 ms-1.5" />
              </Button>
            )}
            {step === 4 && (
              simulation ? (
                <Button variant="primary" onClick={() => setStep(5)}>
                  Continue to approval <ArrowRight className="w-4 h-4 ms-1.5" />
                </Button>
              ) : (
                // Disabled on NOT_READY rather than letting the click fail: the
                // panel above already names every blocker, so the refusal is
                // explained before it happens instead of after.
                <Button
                  variant="primary"
                  onClick={runSimulation}
                  disabled={busy || trust?.status === 'NOT_READY'}
                  title={trust?.status === 'NOT_READY'
                    ? 'Resolve the data readiness blockers above first'
                    : undefined}
                >
                  {busy ? <Loader2 className="w-4 h-4 me-1.5 animate-spin" /> : <TrendingUp className="w-4 h-4 me-1.5" />}
                  Run simulation
                </Button>
              )
            )}
            {step === 5 && (
              <Button variant="primary" onClick={runSubmit} disabled={busy}>
                {busy ? <Loader2 className="w-4 h-4 me-1.5 animate-spin" /> : <Rocket className="w-4 h-4 me-1.5" />}
                Submit for approval
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
