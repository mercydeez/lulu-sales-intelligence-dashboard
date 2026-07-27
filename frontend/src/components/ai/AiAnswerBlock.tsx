import { ReactNode } from 'react';
import { Sparkles, CheckCircle2, ArrowRight } from 'lucide-react';
import { cn } from '@/lib/cn';

export type Confidence = 'high' | 'medium' | 'low';

export interface EvidenceFact { label: string; value: ReactNode }

export interface AiAnswerBlockProps {
  /** 1. the direct answer / verdict — lead with this */
  verdict: ReactNode;
  /** 2. supporting evidence facts (chips) */
  evidence?: EvidenceFact[];
  /** 3. confidence framing (never color-only) */
  confidence?: Confidence;
  /** 4. scope + freshness note, e.g. "Your stores · live data" */
  scope?: ReactNode;
  /** 5. recommended next step */
  nextStep?: ReactNode;
  /** optional AI identity label (defaults to Sage provenance styling) */
  identity?: string;
  className?: string;
}

const CONF: Record<Confidence, { label: string; cls: string }> = {
  high: { label: 'High confidence', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  medium: { label: 'Medium confidence', cls: 'bg-amber-50 text-amber-700 ring-amber-200' },
  low: { label: 'Low confidence', cls: 'bg-surface-2 text-ink-muted ring-line' },
};

/**
 * AI Answer Block — the canonical Sage answer anatomy, in order (AI_EXPERIENCE §4):
 *   verdict → evidence → confidence → scope/freshness → next step.
 * Reused across briefing, copilot, chat, and inline summaries so AI-generated and
 * hand-built surfaces read as one system. Violet accent = AI provenance
 * (VISUAL_LANGUAGE §3), never the primary brand.
 */
export function AiAnswerBlock({
  verdict, evidence, confidence, scope, nextStep, identity = 'Sage', className,
}: AiAnswerBlockProps) {
  return (
    <div className={cn('rounded-2xl bg-surface border border-line shadow-card p-5', className)}>
      <div className="flex items-center gap-1.5 mb-2">
        <Sparkles className="w-3.5 h-3.5" style={{ color: 'var(--ai-600)' }} />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{identity}</span>
        {confidence && (
          <span className={cn('ms-auto inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1', CONF[confidence].cls)}>
            {CONF[confidence].label}
          </span>
        )}
      </div>

      {/* 1. verdict */}
      <div className="text-[15px] leading-relaxed text-ink">{verdict}</div>

      {/* 2. evidence */}
      {evidence && evidence.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {evidence.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded-lg bg-surface-2 px-2 py-1 text-xs text-ink-soft">
              <span className="text-ink-muted">{f.label}</span>
              <span className="font-semibold text-ink tabular-nums">{f.value}</span>
            </span>
          ))}
        </div>
      )}

      {/* 4. scope / freshness */}
      {scope && (
        <p className="mt-3 text-[11px] text-ink-muted flex items-center gap-1.5">
          <CheckCircle2 className="w-3 h-3 shrink-0" />{scope}
        </p>
      )}

      {/* 5. next step */}
      {nextStep && (
        <div className="mt-3 flex items-center gap-1.5 text-sm font-medium text-teal-700">
          <ArrowRight className="w-4 h-4 shrink-0" />{nextStep}
        </div>
      )}
    </div>
  );
}
