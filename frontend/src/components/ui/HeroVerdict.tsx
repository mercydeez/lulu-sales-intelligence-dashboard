import { ReactNode } from 'react';
import { Sparkles } from 'lucide-react';
import { cn } from '@/lib/cn';

/** White text helper for use on the dark hero-mesh (avoids the global text-fill override).
 *  Exported so callers composing slot content (aside/chips/cta) stay legible on the mesh. */
export const onMesh = (o = 1): React.CSSProperties => ({ color: `rgba(255,255,255,${o})`, WebkitTextFillColor: `rgba(255,255,255,${o})` });

export interface HeroVerdictProps {
  /** system/role identity, e.g. "Sage · Store Coach" */
  name: string;
  title?: string;
  /** small line above the verdict, e.g. "Good morning, Atharva" */
  greeting?: ReactNode;
  /** the one summary sentence — the focal moment */
  verdict: ReactNode;
  /** optional italic sub-line (e.g. TLDR) */
  tagline?: ReactNode;
  /** primary CTA + supporting chips/evidence */
  cta?: ReactNode;
  chips?: ReactNode;
  /** right-aligned slot (e.g. a headline number / trend) */
  aside?: ReactNode;
  className?: string;
}

/**
 * Hero Verdict — the focal summary module for Today, Executive Briefing, Copilot,
 * and Public Status (COMPONENT_LIBRARY §4.3). Immersive brand mesh; text forced
 * white so it stays legible over the gradient. AI copy stays grounded, not
 * theatrical (VISUAL_LANGUAGE §4.2).
 */
export function HeroVerdict({
  name, title, greeting, verdict, tagline, cta, chips, aside, className,
}: HeroVerdictProps) {
  return (
    <section className={cn('hero-mesh relative overflow-hidden rounded-3xl p-6 md:p-9 shadow-elevated', className)}>
      <div className="pointer-events-none absolute -top-16 -right-10 w-56 h-56 rounded-full bg-white/10 blur-3xl" />
      <div className="relative z-10">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-white/15 ring-1 ring-white/25 shrink-0">
                <Sparkles className="w-4 h-4 text-white" />
              </span>
              <div className="leading-tight min-w-0">
                <p className="text-sm font-semibold truncate" style={onMesh()}>{name}</p>
                {title && <p className="text-[11px] truncate" style={onMesh(0.7)}>{title}</p>}
              </div>
            </div>

            {greeting && <p className="mt-6 text-sm" style={onMesh(0.75)}>{greeting}</p>}
            <h1 className="mt-1 text-[22px] md:text-[28px] font-semibold leading-[1.3] tracking-[-0.01em] max-w-[46ch]" style={onMesh()}>
              {verdict}
            </h1>
            {tagline && <p className="mt-2 text-sm italic" style={onMesh(0.75)}>{tagline}</p>}
          </div>
          {aside && <div className="shrink-0 text-end">{aside}</div>}
        </div>

        {(cta || chips) && (
          <div className="mt-7 flex flex-wrap items-center gap-3">
            {chips}
            {cta}
          </div>
        )}
      </div>
    </section>
  );
}
