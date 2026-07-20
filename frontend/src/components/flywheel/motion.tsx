'use client';

/**
 * Flywheel motion primitives.
 *
 * STACK NOTE: this repo pins `framer-motion@^11`, not the newer `motion`
 * package, so imports come from 'framer-motion'. Adding a second animation
 * library for one module would bloat the bundle and risk two React contexts.
 * The patterns are identical either way — variants, whileInView,
 * useReducedMotion, and transform/opacity only.
 *
 * MOTION RULES HELD THROUGHOUT:
 *   * Only `transform` and `opacity` animate. Never width/height/top/left.
 *   * Every component checks `useReducedMotion()` and renders a static,
 *     fully-readable fallback — motion is never load-bearing for meaning.
 *   * Entrances are staggered so the eye lands in reading order, once.
 */
import { ReactNode } from 'react';
import { motion, useReducedMotion, type Variants } from 'framer-motion';

/** Shared easing — one curve everywhere reads as designed rather than assembled. */
export const EASE = [0.16, 1, 0.3, 1] as const;

const revealVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0 },
};

export function Reveal({
  children, delay = 0, className,
}: { children: ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      variants={revealVariants}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-8% 0px' }}
      transition={{ duration: 0.55, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  );
}

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.06, delayChildren: 0.04 } },
};
const itemVariants: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: EASE } },
};

export function Stagger({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      variants={containerVariants}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-6% 0px' }}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  return <motion.div className={className} variants={itemVariants}>{children}</motion.div>;
}

/**
 * THE SIGNATURE ELEMENT — the Flywheel loop.
 *
 * "Flywheel" () means *the loop*, and the product's whole thesis is that
 * retention only works when the loop closes: data → intelligence → decision →
 * commercial → execution → measurement → back to data.
 *
 * This is not decoration. The highlighted node is the stage the campaign is
 * ACTUALLY in, derived from its persisted status — so the brand's central
 * metaphor doubles as the primary status indicator. Spending the boldness here
 * lets every other surface stay quiet.
 *
 * Accessibility: the ring is `role="img"` with a label naming the current stage,
 * and the same information is repeated as text beneath it, so nothing is
 * conveyed by colour or position alone.
 */
const STAGES = [
  { key: 'DATA', label: 'Data', hint: 'customers, events, inventory' },
  { key: 'INTELLIGENCE', label: 'Intelligence', hint: 'churn + uplift' },
  { key: 'DECISION', label: 'Decision', hint: 'next-best action by EIV' },
  { key: 'COMMERCIAL', label: 'Commercial', hint: 'stock, budget, approval' },
  { key: 'EXECUTION', label: 'Execution', hint: 'live offers & redemption' },
  { key: 'MEASUREMENT', label: 'Measurement', hint: 'true lift vs control' },
] as const;

export type LoopStage = typeof STAGES[number]['key'];

/** Map a campaign status onto the loop stage it occupies. */
export function stageForStatus(status?: string): LoopStage {
  switch (status) {
    case 'DRAFT': return 'DATA';
    case 'AUDIENCE_READY': return 'INTELLIGENCE';
    case 'SIMULATED': return 'DECISION';
    case 'PENDING_INVENTORY_REVIEW':
    case 'PENDING_PROCUREMENT_REVIEW':
    case 'PENDING_FINANCE_APPROVAL':
    case 'PENDING_MARKETING_APPROVAL':
    case 'APPROVED':
    case 'SCHEDULED': return 'COMMERCIAL';
    case 'ACTIVE':
    case 'PAUSED': return 'EXECUTION';
    case 'COMPLETED':
    case 'MEASURED': return 'MEASUREMENT';
    default: return 'DATA';
  }
}

export function LoopRing({
  activeStage = 'DATA', size = 260, className,
}: { activeStage?: LoopStage; size?: number; className?: string }) {
  const reduce = useReducedMotion();
  const cx = 160, cy = 160, r = 112;
  const activeIndex = STAGES.findIndex((s) => s.key === activeStage);
  const current = STAGES[activeIndex] ?? STAGES[0];

  // Six evenly spaced nodes, starting at 12 o'clock and running clockwise.
  const nodes = STAGES.map((stage, i) => {
    const angle = (i / STAGES.length) * 2 * Math.PI - Math.PI / 2;
    return { ...stage, x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle), index: i };
  });

  return (
    <div className={className}>
      <svg
        viewBox="0 0 320 320"
        width={size}
        height={size}
        role="img"
        aria-label={`The Flywheel retention loop, six stages. Current stage: ${current.label} — ${current.hint}.`}
        className="max-w-full h-auto"
      >
        <circle cx={cx} cy={cy} r={r} fill="none"
                className="stroke-slate-200 dark:stroke-slate-700" strokeWidth={2} />

        {/* The travelling arc: a rotating dash that reads as circulation.
            Rotation is a transform, so it stays on the compositor. */}
        {!reduce && (
          <motion.circle
            cx={cx} cy={cy} r={r} fill="none"
            className="stroke-teal-500" strokeWidth={2.5} strokeLinecap="round"
            strokeDasharray="70 634"
            initial={{ rotate: 0 }}
            animate={{ rotate: 360 }}
            transition={{ duration: 14, repeat: Infinity, ease: 'linear' }}
            style={{ transformOrigin: `${cx}px ${cy}px` }}
          />
        )}

        {nodes.map((node) => {
          const isActive = node.key === activeStage;
          const isPast = node.index < activeIndex;
          return (
            <g key={node.key}>
              {isActive && !reduce && (
                <motion.circle
                  cx={node.x} cy={node.y} r={17}
                  className="fill-teal-500/25"
                  initial={{ scale: 1, opacity: 0.7 }}
                  animate={{ scale: [1, 1.55, 1], opacity: [0.7, 0, 0.7] }}
                  transition={{ duration: 2.4, repeat: Infinity, ease: 'easeOut' }}
                  style={{ transformOrigin: `${node.x}px ${node.y}px` }}
                />
              )}
              <circle
                cx={node.x} cy={node.y} r={isActive ? 17 : 13}
                className={
                  isActive ? 'fill-teal-600'
                    : isPast ? 'fill-teal-300 dark:fill-teal-700'
                      : 'fill-slate-300 dark:fill-slate-600'
                }
              />
              <text
                x={node.x} y={node.y + 4} textAnchor="middle"
                className="fill-white font-mono font-bold"
                fontSize={isActive ? 13 : 11}
              >
                {node.index + 1}
              </text>
            </g>
          );
        })}

        <text x={cx} y={cy - 10} textAnchor="middle"
              className="fill-slate-400 dark:fill-slate-500 font-mono"
              fontSize={10} letterSpacing={2}>CLOSED</text>
        <text x={cx} y={cy + 12} textAnchor="middle"
              className="fill-slate-900 dark:fill-slate-100 font-bold" fontSize={20}>LOOP</text>
        <text x={cx} y={cy + 29} textAnchor="middle"
              className="fill-slate-400 dark:fill-slate-500" fontSize={9.5}>
          {current.label}
        </text>
      </svg>

      {/* The same information as text — never colour/position alone. */}
      <ol className="mt-4 grid gap-1.5 text-xs">
        {STAGES.map((stage, i) => {
          const isActive = stage.key === activeStage;
          return (
            <li key={stage.key}
                className={`flex items-baseline gap-2 ${isActive ? 'font-semibold text-teal-700 dark:text-teal-300' : 'text-slate-500 dark:text-slate-400'}`}>
              <span className="font-mono text-[10px] w-4 shrink-0">{i + 1}</span>
              <span>{stage.label}</span>
              <span className="text-slate-400 dark:text-slate-500 font-normal">— {stage.hint}</span>
              {isActive && <span className="sr-only">(current stage)</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * The synthetic-data label. Required on every Flywheel surface (§20) — the product
 * makes claims about customer behaviour, and the reader must never be left
 * guessing whether those customers are real. They are not.
 */
export function SyntheticBadge({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-amber-300/60
                  bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-800
                  dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300 ${className}`}
      title="All customers, events and campaign outcomes in Flywheel are synthetic. No production accuracy is claimed."
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-amber-500" />
      Synthetic data
    </span>
  );
}

/**
 * A horizontal EIV waterfall — benefits in teal, costs in amber, net in the
 * brand colour. Bars are SVG rects sized by percentage of the largest absolute
 * term, so a 0.05 AED comms cost never renders as an invisible sliver next to
 * a 500 AED retained value.
 *
 * Animating `scaleX` from a left origin (not `width`) keeps this off the layout
 * path at 60fps.
 */
export function EivWaterfall({
  terms, className,
}: {
  terms: Array<{ label: string; value: number; kind: 'benefit' | 'cost' | 'net' }>;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const max = Math.max(...terms.map((t) => Math.abs(t.value)), 1);

  return (
    <div className={className}>
      <ul className="space-y-2">
        {terms.map((term, i) => {
          const width = Math.max(1.5, (Math.abs(term.value) / max) * 100);
          const tone =
            term.kind === 'net'
              ? (term.value >= 0 ? 'bg-teal-600' : 'bg-rose-500')
              : term.kind === 'benefit' ? 'bg-teal-400' : 'bg-amber-400';
          return (
            <li key={term.label} className="grid grid-cols-[1fr_auto] gap-x-3 items-center">
              <div className="min-w-0">
                <div className="flex items-baseline justify-between gap-2">
                  <span className={`truncate text-xs ${term.kind === 'net'
                    ? 'font-semibold text-slate-900 dark:text-slate-100'
                    : 'text-slate-600 dark:text-slate-400'}`}>
                    {term.label}
                  </span>
                </div>
                <div className="mt-1 h-2 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                  {reduce ? (
                    <div className={`h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
                  ) : (
                    <motion.div
                      className={`h-full rounded-full origin-left ${tone}`}
                      style={{ width: `${width}%` }}
                      initial={{ scaleX: 0 }}
                      whileInView={{ scaleX: 1 }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.6, ease: EASE, delay: i * 0.05 }}
                    />
                  )}
                </div>
              </div>
              <span className={`font-mono text-xs tabular-nums ${
                term.kind === 'net'
                  ? (term.value >= 0 ? 'text-teal-700 dark:text-teal-300 font-semibold'
                                     : 'text-rose-600 dark:text-rose-400 font-semibold')
                  : term.kind === 'cost' ? 'text-amber-700 dark:text-amber-400'
                                         : 'text-slate-700 dark:text-slate-300'
              }`}>
                {term.kind === 'cost' && term.value !== 0 ? '−' : ''}
                {new Intl.NumberFormat('en-AE', { minimumFractionDigits: 2,
                  maximumFractionDigits: 2 }).format(Math.abs(term.value))}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * The approval chain. Steps sharing a `parallel_group` are drawn side by side
 * because they genuinely run concurrently — drawing them as a single queue
 * would misrepresent the workflow and make people wait for each other.
 */
export function ApprovalChain({
  steps, onDecide, busy,
}: {
  steps: Array<{
    step_id: number; step_order: number; label: string; status: string;
    required_role: string; decided_by?: string | null; comment?: string | null;
    can_decide?: boolean;
  }>;
  onDecide?: (stepId: number, decision: string) => void;
  busy?: boolean;
}) {
  const reduce = useReducedMotion();
  const groups = Array.from(new Set(steps.map((s) => s.step_order))).sort((a, b) => a - b);

  const tone = (status: string) =>
    status === 'approved' ? 'border-teal-400 bg-teal-50 dark:bg-teal-500/10'
      : status === 'rejected' ? 'border-rose-400 bg-rose-50 dark:bg-rose-500/10'
        : status === 'changes_requested' ? 'border-amber-400 bg-amber-50 dark:bg-amber-500/10'
          : 'border-slate-200 dark:border-slate-700';

  return (
    <ol className="space-y-3">
      {groups.map((group, gi) => {
        const groupSteps = steps.filter((s) => s.step_order === group);
        const isParallel = groupSteps.length > 1;
        return (
          <li key={group}>
            <div className="mb-1.5 flex items-center gap-2 text-[11px] uppercase tracking-wider text-slate-400">
              <span>Stage {gi + 1}</span>
              {isParallel && (
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                  {groupSteps.length} in parallel
                </span>
              )}
            </div>
            <div className={`grid gap-2 ${isParallel ? 'sm:grid-cols-2' : ''}`}>
              {groupSteps.map((step, si) => {
                const card = (
                  <div className={`rounded-lg border p-3 ${tone(step.status)}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                          {step.label}
                        </p>
                        <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                          {step.required_role.replace(/_/g, ' ')}
                        </p>
                      </div>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                        step.status === 'approved' ? 'bg-teal-600 text-white'
                          : step.status === 'rejected' ? 'bg-rose-600 text-white'
                            : step.status === 'changes_requested' ? 'bg-amber-500 text-white'
                              : 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                      }`}>
                        {step.status === 'changes_requested' ? 'changes' : step.status}
                      </span>
                    </div>

                    {step.decided_by && (
                      <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
                        by {step.decided_by}
                        {step.comment ? ` — “${step.comment}”` : ''}
                      </p>
                    )}

                    {step.status === 'pending' && onDecide && (
                      step.can_decide ? (
                        <div className="mt-3 flex gap-2">
                          <button
                            type="button" disabled={busy}
                            onClick={() => onDecide(step.step_id, 'approved')}
                            className="rounded-md bg-teal-700 px-3 py-1.5 text-xs font-medium text-white
                                       hover:bg-teal-800 focus-visible:outline focus-visible:outline-2
                                       focus-visible:outline-offset-2 focus-visible:outline-teal-600
                                       disabled:opacity-50"
                          >
                            Approve
                          </button>
                          <button
                            type="button" disabled={busy}
                            onClick={() => onDecide(step.step_id, 'rejected')}
                            className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium
                                       text-slate-700 hover:bg-slate-50 focus-visible:outline
                                       focus-visible:outline-2 focus-visible:outline-offset-2
                                       focus-visible:outline-slate-400 disabled:opacity-50
                                       dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
                          >
                            Reject
                          </button>
                        </div>
                      ) : (
                        // Show WHY the button is absent rather than hiding the
                        // work — an operator who cannot act should still know
                        // who can.
                        <p className="mt-3 text-[11px] italic text-slate-400">
                          Awaiting {step.required_role.replace(/_/g, ' ')} — you cannot act on this step
                        </p>
                      )
                    )}
                  </div>
                );
                return reduce ? (
                  <div key={step.step_id}>{card}</div>
                ) : (
                  <motion.div
                    key={step.step_id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4, ease: EASE, delay: gi * 0.08 + si * 0.05 }}
                  >
                    {card}
                  </motion.div>
                );
              })}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
