'use client';

/**
 * The data-trust verdict, shown where it changes what the operator does.
 *
 * WHY IT LOOKS LIKE THIS.
 *
 * The server refuses to simulate or activate on NOT_READY. Without this panel
 * the operator fills in four wizard steps, presses Run simulation, and gets a
 * flat refusal — effort already spent, no idea which of a dozen inputs is at
 * fault. So the verdict is fetched when they ARRIVE at the simulation step and
 * rendered before the button, turning a dead end into a checklist.
 *
 * A clean result stays QUIET — one line, no card, no colour block. Shouting
 * "READY" in green every time trains people to ignore the strip, and then the
 * one time it says NOT_READY they ignore that too. Attention is spent only when
 * something is actually wrong.
 *
 * Severity drives colour, and colour is never the only signal: every state also
 * carries an icon and a word, so it survives greyscale and colour-blindness.
 * Blocking findings are `role="alert"`; everything else is `role="status"`.
 */
import { AlertTriangle, CheckCircle2, Loader2, ShieldAlert, Info } from 'lucide-react';
import type { DataTrustReport } from '@/types/flywheel';

export interface DataTrustPanelProps {
  report: DataTrustReport | null;
  loading?: boolean;
  /** Set when the check itself could not run. Never blocks the wizard — an
   *  unreachable checker is not evidence that the data is bad. */
  unavailable?: string | null;
  className?: string;
}

const TONE = {
  READY: {
    label: 'Ready',
    icon: CheckCircle2,
    text: 'text-emerald-700 dark:text-emerald-400',
    border: 'border-emerald-200 dark:border-emerald-500/30',
    bg: 'bg-emerald-50/60 dark:bg-emerald-500/5',
  },
  READY_WITH_WARNINGS: {
    label: 'Ready, with warnings',
    icon: AlertTriangle,
    text: 'text-amber-800 dark:text-amber-300',
    border: 'border-amber-300 dark:border-amber-500/30',
    bg: 'bg-amber-50 dark:bg-amber-500/10',
  },
  NOT_READY: {
    label: 'Not ready',
    icon: ShieldAlert,
    text: 'text-rose-800 dark:text-rose-300',
    border: 'border-rose-300 dark:border-rose-500/30',
    bg: 'bg-rose-50 dark:bg-rose-500/10',
  },
} as const;

export function DataTrustPanel({ report, loading, unavailable, className }: DataTrustPanelProps) {
  if (loading) {
    return (
      <p role="status" className={`flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 ${className ?? ''}`}>
        <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" />
        Checking whether the input data can be trusted…
      </p>
    );
  }

  if (unavailable) {
    return (
      <p role="status" className={`flex items-start gap-2 text-xs text-slate-500 dark:text-slate-400 ${className ?? ''}`}>
        <Info aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          Could not check data readiness ({unavailable}). The simulation will still
          apply the check server-side.
        </span>
      </p>
    );
  }

  if (!report) return null;

  const tone = TONE[report.status] ?? TONE.READY_WITH_WARNINGS;
  const Icon = tone.icon;
  const blocking = report.status === 'NOT_READY';

  // Clean run: a single quiet line. No card, no fill — see the note above.
  if (report.status === 'READY') {
    return (
      <p role="status" className={`flex items-center gap-2 text-xs ${tone.text} ${className ?? ''}`}>
        <Icon aria-hidden className="h-3.5 w-3.5" />
        <span>
          Data ready — {report.scope.items_evaluated} items and{' '}
          {report.scope.stores_evaluated} stores checked, nothing to flag.
        </span>
      </p>
    );
  }

  // Blockers first: they are the reason the button will refuse.
  const ordered = [...report.findings].sort(
    (a, b) => (a.severity === 'block' ? 0 : 1) - (b.severity === 'block' ? 0 : 1));

  return (
    <section
      role={blocking ? 'alert' : 'status'}
      aria-label="Data readiness"
      className={`rounded-lg border p-4 ${tone.border} ${tone.bg} ${className ?? ''}`}
    >
      <div className="flex items-start gap-2">
        <Icon aria-hidden className={`mt-0.5 h-4 w-4 shrink-0 ${tone.text}`} />
        <div className="min-w-0">
          <h3 className={`text-sm font-semibold ${tone.text}`}>
            Data readiness — {tone.label}
          </h3>
          <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-400">
            {blocking
              ? 'The simulation is blocked until these are resolved. Every number it '
                + 'produced would be derived from input that is known to be wrong.'
              : 'The simulation will run. These caveats apply to the numbers it returns.'}
          </p>
        </div>
      </div>

      <ul className="mt-3 space-y-2">
        {ordered.map((f) => (
          <li key={f.code} className="flex items-start gap-2 text-xs">
            <span
              className={`mt-px shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                f.severity === 'block'
                  ? 'bg-rose-200/70 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200'
                  : 'bg-amber-200/70 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200'
              }`}
            >
              {f.severity === 'block' ? 'Blocks' : 'Warns'}
            </span>
            {/* The trailing space is load-bearing: without it the detail and the
                code concatenate into one run-on word for screen readers and any
                text extraction, even though the margin separates them visually. */}
            <span className="min-w-0 text-slate-700 dark:text-slate-300">
              {f.detail}{' '}
              <code className="ms-1.5 text-[10px] text-slate-400">{f.code}</code>
            </span>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-[11px] text-slate-500 dark:text-slate-400">
        Checked {report.scope.items_evaluated} items across{' '}
        {report.scope.stores_evaluated} store(s). The same check runs server-side
        on simulate and again on activate.
      </p>
    </section>
  );
}
