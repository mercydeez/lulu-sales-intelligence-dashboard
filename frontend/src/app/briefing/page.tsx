'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { useAuth } from '@/contexts/AuthContext';
import { Button, ErrorState, Reveal, ScrollReveal, AnimatedNumber } from '@/components/ui';
import { apiGet, authFetch, ApiError } from '@/lib/apiClient';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import {
  Sparkles, RefreshCw, Download, ArrowUpRight, ArrowDownRight, ArrowRight, Minus,
  AlertTriangle, CalendarClock, Wallet, Trophy, ChevronRight, Sunrise,
} from 'lucide-react';

const AED = (n: number | null | undefined, dp = 0) =>
  n == null ? '—' : `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: dp, minimumFractionDigits: dp })}`;

interface Change { title: string; detail?: string; severity: string; entity?: string; category?: string; href: string }
interface Decision { title: string; why: string; action: string; urgency: string; href: string; kind: string }
interface Win { title: string; detail: string; kind: string }
interface Season { name: string; active: boolean; days_until: number; note: string; approx: boolean }
interface Forecast { horizon_days: number; projected_revenue_aed: number; avg_daily_revenue_aed: number }
interface Watch { season: Season | null; forecast: Forecast | null; summary: string }
interface Leak { dead_stock_aed: number; stockout_loss_aed: number; total_aed: number; note: string }
interface Headline {
  revenue_aed: number; revenue_change_pct: number | null; units: number;
  units_change_pct: number | null; trend: string; period_label: string; summary: string;
}
interface Briefing {
  date: string; generated_at: string | null; tenant_name: string; greeting: string;
  tldr: string; headline: Headline; changes: Change[]; decisions: Decision[];
  win: Win | null; watch: Watch; leak: Leak;
  counts: { open_findings: number; decisions: number; reorder_risks: number };
  empty: boolean;
}

type Mood = 'strong' | 'steady' | 'soft' | 'attention';

const SEV_HEX: Record<string, string> = {
  critical: '#f43f5e', high: '#f97316', medium: '#f59e0b', low: 'var(--brand)',
};
const SEV_TEXT: Record<string, string> = {
  critical: 'text-rose-600 dark:text-rose-400', high: 'text-orange-600 dark:text-orange-400', medium: 'text-amber-600 dark:text-amber-400', low: 'text-teal-600 dark:text-teal-300',
};
/** Logical (RTL-correct) colored accent bar on the inline-start edge. */
const sevBar = (sev: string): React.CSSProperties => ({
  borderInlineStartWidth: '3px', borderInlineStartColor: SEV_HEX[sev] ?? SEV_HEX.low,
});

/** Lowercase a decision title for mid-sentence use, but keep acronyms/first-caps names. */
function midSentence(s: string): string {
  if (!s) return s;
  // Keep it as-is if it starts with a proper noun-ish capital run; else lowercase the first letter.
  return /^[A-Z][a-z]/.test(s) ? s.charAt(0).toLowerCase() + s.slice(1) : s;
}

/** Compose Sage's spoken verdict from the briefing data — the AI-COO voice. */
function narrate(b: Briefing, firstName: string) {
  const pct = b.headline.revenue_change_pct;
  const trend = b.headline.trend;
  const top = b.decisions[0] ?? null;
  const critical = b.decisions.some((d) => d.urgency === 'critical');
  const revenue = AED(b.headline.revenue_aed);

  const mood: Mood = critical ? 'attention' : trend === 'up' ? 'strong' : trend === 'down' ? 'soft' : 'steady';

  const opener: Record<Mood, string> = {
    strong: `It's a strong morning.`,
    steady: `A steady start.`,
    soft: `A softer morning.`,
    attention: `Good news first, then one thing that needs you.`,
  };

  const movement =
    pct == null ? `Revenue is at ${revenue} so far this week`
      : trend === 'up' ? `Revenue is ahead ${Math.abs(pct)}% week-over-week at ${revenue}`
        : trend === 'down' ? `Revenue is off ${Math.abs(pct)}% week-over-week at ${revenue}`
          : `Revenue is holding steady this week at ${revenue}`;

  const focus = top
    ? `The one call for you today: ${midSentence(top.title)}.`
    : `Nothing needs a decision from you — you're clear to lead the day.`;

  const greeting = `${b.greeting}${firstName ? `, ${firstName}` : ''}.`;
  const line = `${opener[mood]} ${movement}. ${focus}`;

  return { mood, greeting, line, top };
}

const MOOD_PILL: Record<Mood, string> = {
  strong: 'bg-emerald-400/15 text-emerald-50 ring-1 ring-emerald-300/30',
  steady: 'bg-white/10 text-white ring-1 ring-white/20',
  soft: 'bg-amber-400/15 text-amber-50 ring-1 ring-amber-300/30',
  attention: 'bg-amber-400/20 text-amber-50 ring-1 ring-amber-200/40',
};

/** Character-by-character reveal for Sage's verdict. Falls back to instant text
 *  under prefers-reduced-motion. */
function useTypewriter(text: string, active: boolean, speed = 15) {
  const reduced = useReducedMotion();
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!active) { setN(0); return; }
    if (reduced) { setN(text.length); return; }
    setN(0);
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setN(i);
      if (i >= text.length) clearInterval(id);
    }, speed);
    return () => clearInterval(id);
  }, [text, active, reduced, speed]);
  return { shown: text.slice(0, n), done: n >= text.length };
}

export default function BriefingPage() {
  const { user } = useAuth();
  const [b, setB] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [printing, setPrinting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setB(await apiGet<Briefing>('/api/briefing')); }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Failed to load your briefing'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const downloadBrief = async () => {
    setPrinting(true);
    try {
      const res = await authFetch('/api/briefing/print');
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `daily-briefing-${b?.date ?? 'today'}.html`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } finally { setPrinting(false); }
  };

  const rawName = (user?.email ?? '').split('@')[0].split(/[._-]/)[0];
  const firstName = rawName ? rawName.charAt(0).toUpperCase() + rawName.slice(1) : '';

  return (
    <main className="min-h-screen px-4 md:px-8 py-6 md:py-10">
      <div className="max-w-3xl mx-auto">
        {loading ? (
          <BriefingLoading />
        ) : error ? (
          <div className="pt-6"><ErrorState title="Couldn't reach Sage" description={error} onRetry={load} /></div>
        ) : b && b.empty ? (
          <EmptyBrief firstName={firstName} />
        ) : b && (
          <BriefingContent b={b} firstName={firstName} onRefresh={load} loading={loading}
            onDownload={downloadBrief} printing={printing} />
        )}
      </div>
    </main>
  );
}

function BriefingContent({ b, firstName, onRefresh, loading, onDownload, printing }: {
  b: Briefing; firstName: string; onRefresh: () => void; loading: boolean;
  onDownload: () => void; printing: boolean;
}) {
  const { mood, greeting, line, top } = narrate(b, firstName);
  const { shown, done } = useTypewriter(line, true);
  const rest = b.decisions.slice(1);
  const now = new Date();
  const clock = now.toLocaleTimeString('en-AE', { hour: 'numeric', minute: '2-digit' });
  const weekday = now.toLocaleDateString('en-AE', { weekday: 'long', day: 'numeric', month: 'long' });

  const trendIcon = b.headline.trend === 'up' ? ArrowUpRight : b.headline.trend === 'down' ? ArrowDownRight : Minus;
  const TrendIcon = trendIcon;
  const trendColor = b.headline.trend === 'up' ? 'text-emerald-600' : b.headline.trend === 'down' ? 'text-rose-600' : 'text-ink-muted';

  return (
    <div className="space-y-10">
      {/* ── THE BRIEF: Sage's morning verdict (the 30-second AI-COO moment) ── */}
      <Reveal>
        <section className="hero-mesh relative overflow-hidden rounded-3xl p-7 md:p-10 shadow-elevated">
          {/* ambient depth */}
          <div className="pointer-events-none absolute -top-16 -right-10 w-56 h-56 rounded-full bg-white/10 blur-3xl animate-float" />
          <div className="pointer-events-none absolute -bottom-20 -left-10 w-64 h-64 rounded-full bg-violet-400/10 blur-3xl animate-float" style={{ animationDelay: '1.2s' }} />

          <div className="relative z-10">
            {/* Sage identity */}
            <div className="flex items-center gap-3">
              <span className="relative flex items-center justify-center w-9 h-9 rounded-2xl bg-white/15 ring-1 ring-white/25">
                <Sparkles className="w-5 h-5 text-white" />
                <span className="absolute inset-0 rounded-2xl animate-pulse-glow" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-white leading-tight">Sage</p>
                <p className="text-[11px] text-white/70 leading-tight">Your AI Chief of Staff</p>
              </div>
              <span className="ms-auto text-[11px] text-white/70 tabular-nums">{clock} · {weekday}</span>
            </div>

            {/* Greeting + verdict (typed) */}
            <p className="mt-7 text-sm" style={{ color: 'rgba(255,255,255,0.75)', WebkitTextFillColor: 'rgba(255,255,255,0.75)' }}>{greeting}</p>
            <h1 className="mt-1 text-[26px] md:text-[32px] font-semibold leading-[1.28] tracking-[-0.01em] max-w-[42ch]"
              style={{ color: '#fff', WebkitTextFillColor: '#fff' }}>
              {shown}
              {!done && <span className="inline-block w-[2px] h-[1.05em] -mb-[0.16em] ms-0.5 bg-white/80 animate-pulse" />}
            </h1>

            {/* status + primary call — fade in once Sage finishes speaking */}
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={done ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              className="mt-7 flex flex-wrap items-center gap-3"
            >
              <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${MOOD_PILL[mood]}`}>
                <span className="w-1.5 h-1.5 rounded-full bg-current opacity-80" />
                {b.counts.decisions > 0
                  ? `${b.counts.decisions} ${b.counts.decisions === 1 ? 'decision' : 'decisions'} for you`
                  : 'Nothing needs a decision'}
              </span>
              {top ? (
                <Link href={top.href}
                  className="inline-flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-sm font-semibold text-teal-800 shadow-sm hover:bg-white/90 active:scale-[0.98] transition">
                  Take me to it <ArrowRight className="w-4 h-4" />
                </Link>
              ) : (
                <Link href="/insights"
                  className="inline-flex items-center gap-1.5 rounded-full bg-white/15 ring-1 ring-white/25 px-4 py-2 text-sm font-semibold text-white hover:bg-white/25 transition">
                  Explore insights <ArrowRight className="w-4 h-4" />
                </Link>
              )}
            </motion.div>
          </div>
        </section>
      </Reveal>

      {/* ── WHAT NEEDS YOU: the single focal decision ── */}
      {top && (
        <Reveal delay={0.15}>
          <section>
            <SectionLabel icon={<AlertTriangle className="w-3.5 h-3.5" />}>What needs you</SectionLabel>
            <div className="rounded-2xl bg-surface border border-line shadow-card p-5 md:p-6" style={sevBar(top.urgency)}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-[11px] font-bold uppercase tracking-wide ${SEV_TEXT[top.urgency] ?? 'text-teal-600'}`}>{top.urgency}</span>
                  </div>
                  <h3 className="mt-1 text-xl font-semibold text-ink leading-snug">{top.title}</h3>
                  <p className="mt-1.5 text-[15px] leading-relaxed text-ink-soft">{top.why}</p>
                </div>
              </div>
              {/* Sage's recommendation */}
              <div className="mt-4 flex items-start gap-2.5 rounded-xl bg-teal-50/70 ring-1 ring-teal-100 p-3.5">
                <Sparkles className="w-4 h-4 text-teal-600 mt-0.5 shrink-0" />
                <p className="text-sm text-teal-900"><span className="font-semibold">Sage suggests:</span> {top.action}.</p>
              </div>
              <div className="mt-4">
                <Link href={top.href}><Button size="md">Review &amp; act <ArrowRight className="w-4 h-4 ms-1" /></Button></Link>
              </div>
            </div>

            {/* secondary decisions, compact */}
            {rest.length > 0 && (
              <div className="mt-3 rounded-2xl bg-surface border border-line divide-y divide-line">
                {rest.map((d, i) => (
                  <Link key={i} href={d.href}
                    className="flex items-center gap-3 px-4 py-3 hover:bg-surface-2 transition-colors group first:rounded-t-2xl last:rounded-b-2xl">
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${(SEV_TEXT[d.urgency] ?? 'text-teal-600').replace('text-', 'bg-')}`} />
                    <span className="text-sm text-ink font-medium truncate">{d.title}</span>
                    <span className="text-xs text-ink-muted truncate hidden sm:block">— {d.action}</span>
                    <ChevronRight className="w-4 h-4 text-ink-muted ms-auto shrink-0 group-hover:translate-x-0.5 transition-transform" />
                  </Link>
                ))}
              </div>
            )}
          </section>
        </Reveal>
      )}

      {/* ── THE NUMBERS: editorial, one confident line ── */}
      <Reveal delay={0.2}>
        <section>
          <SectionLabel>This morning&apos;s numbers</SectionLabel>
          <div className="rounded-2xl bg-surface border border-line shadow-card p-5 md:p-6">
            <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
              <div>
                <p className="text-[11px] uppercase tracking-widest text-ink-muted">{b.headline.period_label}</p>
                <div className="mt-1 flex items-baseline gap-2.5">
                  <span className="text-4xl md:text-5xl font-bold tracking-tight text-ink tabular-nums">
                    <AnimatedNumber value={b.headline.revenue_aed} formatter={(n) => AED(n)} />
                  </span>
                  {b.headline.revenue_change_pct != null && (
                    <span className={`inline-flex items-center gap-0.5 text-sm font-semibold ${trendColor}`}>
                      <TrendIcon className="w-4 h-4" />
                      {b.headline.revenue_change_pct > 0 ? '+' : ''}{b.headline.revenue_change_pct}%
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-end gap-6 md:gap-8 ms-auto">
                <Stat label="Volume" value={`${b.headline.units.toLocaleString()}`} sub="units" />
                {b.watch.forecast && (
                  <Stat label={`Next ${b.watch.forecast.horizon_days}d`} value={AED(b.watch.forecast.projected_revenue_aed)} sub="forecast" />
                )}
                <Stat label="At risk" value={AED(b.leak.total_aed)} sub="if unactioned" tone="amber" />
              </div>
            </div>
          </div>
        </section>
      </Reveal>

      {/* ── WHY IT'S MOVING: the changes as a tight narrative ── */}
      {b.changes.length > 0 && (
        <ScrollReveal>
          <section>
            <SectionLabel icon={<Sunrise className="w-3.5 h-3.5" />} href="/insights" linkLabel="All insights">
              Why it&apos;s moving
            </SectionLabel>
            <div className="space-y-2.5">
              {b.changes.map((c, i) => (
                <div key={i} className="rounded-xl bg-surface border border-line px-4 py-3" style={sevBar(c.severity)}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-[15px] font-medium text-ink">{c.title}</p>
                    {c.entity && <span className="text-xs text-ink-muted">· {c.entity}</span>}
                  </div>
                  {c.detail && <p className="text-sm text-ink-soft mt-0.5">{c.detail}</p>}
                </div>
              ))}
            </div>
          </section>
        </ScrollReveal>
      )}

      {/* ── ON YOUR RADAR: horizon + cost of inaction ── */}
      <ScrollReveal>
        <section>
          <SectionLabel icon={<CalendarClock className="w-3.5 h-3.5" />}>On your radar</SectionLabel>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded-2xl bg-surface border border-line shadow-card p-5">
              {b.watch.season ? (
                <>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-ink">{b.watch.season.name}</p>
                    {b.watch.season.active
                      ? <span className="text-[11px] font-medium text-violet-700 bg-violet-50 rounded-full px-2 py-0.5">live now</span>
                      : <span className="text-[11px] font-medium text-ink-muted bg-surface-2 rounded-full px-2 py-0.5">in {b.watch.season.days_until} days</span>}
                  </div>
                  <p className="text-sm text-ink-soft mt-1.5 leading-relaxed">{b.watch.season.note}</p>
                  {b.watch.season.approx && <p className="text-[11px] text-ink-muted mt-1.5">Lunar date — confirm before ordering.</p>}
                </>
              ) : (
                <p className="text-sm text-ink-muted">No major UAE retail events on the near horizon.</p>
              )}
            </div>
            <div className="rounded-2xl bg-amber-50/50 border border-amber-100 p-5">
              <div className="flex items-center gap-2">
                <Wallet className="w-4 h-4 text-amber-600" />
                <p className="text-[11px] uppercase tracking-widest text-amber-700 font-semibold">Cost of waiting</p>
              </div>
              <p className="mt-1.5 text-3xl font-bold text-amber-700 tabular-nums">{AED(b.leak.total_aed)}</p>
              <p className="text-sm text-amber-800/80 mt-1 leading-relaxed">{b.leak.note}</p>
              <Link href="/value" className="inline-flex items-center gap-1 text-sm font-medium text-amber-700 hover:text-amber-800 mt-2.5">
                Full breakdown <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>
        </section>
      </ScrollReveal>

      {/* ── THE WIN: quiet, positive close ── */}
      {b.win && (
        <ScrollReveal>
          <div className="flex items-start gap-3 rounded-2xl bg-emerald-50/60 border border-emerald-100 px-5 py-4">
            <Trophy className="w-5 h-5 text-emerald-600 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-semibold text-emerald-900">{b.win.title}</p>
              <p className="text-sm text-emerald-800/80 mt-0.5 leading-relaxed">{b.win.detail}</p>
            </div>
          </div>
        </ScrollReveal>
      )}

      {/* ── Signature / actions ── */}
      <div className="flex items-center justify-between gap-3 pt-2 border-t border-line">
        <p className="text-xs text-ink-muted flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-teal-500" />
          Briefed by Sage from your live data · {b.tenant_name}
        </p>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onDownload} disabled={printing}>
            <Download className={`w-4 h-4 me-1.5 ${printing ? 'animate-pulse' : ''}`} /> Email brief
          </Button>
          <Button variant="ghost" size="sm" onClick={onRefresh} aria-label="Refresh briefing">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>
    </div>
  );
}

function SectionLabel({ children, icon, href, linkLabel }: {
  children: React.ReactNode; icon?: React.ReactNode; href?: string; linkLabel?: string;
}) {
  return (
    <div className="flex items-center justify-between mb-3">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
        {icon}{children}
      </p>
      {href && (
        <Link href={href} className="text-xs font-medium text-teal-600 hover:text-teal-700">{linkLabel ?? 'View'} →</Link>
      )}
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'amber' }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-widest text-ink-muted">{label}</p>
      <p className={`text-lg font-semibold tabular-nums mt-0.5 ${tone === 'amber' ? 'text-amber-700' : 'text-ink'}`}>{value}</p>
      {sub && <p className="text-[11px] text-ink-muted">{sub}</p>}
    </div>
  );
}

/** Premium loading — Sage "reading your stores", not a generic spinner. */
function BriefingLoading() {
  return (
    <div className="space-y-10">
      <div className="hero-mesh relative overflow-hidden rounded-3xl p-7 md:p-10 shadow-elevated">
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <span className="relative flex items-center justify-center w-9 h-9 rounded-2xl bg-white/15 ring-1 ring-white/25">
              <Sparkles className="w-5 h-5 text-white" />
              <span className="absolute inset-0 rounded-2xl animate-pulse-glow" />
            </span>
            <div>
              <p className="text-sm font-semibold text-white leading-tight">Sage</p>
              <p className="text-[11px] text-white/70 leading-tight flex items-center gap-1.5">
                reading your stores
                <span className="inline-flex gap-1">
                  <span className="w-1 h-1 rounded-full bg-white/70 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1 h-1 rounded-full bg-white/70 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1 h-1 rounded-full bg-white/70 animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
              </p>
            </div>
          </div>
          <div className="mt-7 space-y-3">
            <div className="h-6 w-3/4 rounded-lg bg-white/15 animate-pulse" />
            <div className="h-6 w-2/3 rounded-lg bg-white/10 animate-pulse" />
            <div className="h-6 w-1/2 rounded-lg bg-white/10 animate-pulse" />
          </div>
        </div>
      </div>
      <div className="space-y-3">
        <div className="h-28 rounded-2xl bg-surface border border-line animate-pulse" />
        <div className="h-24 rounded-2xl bg-surface border border-line animate-pulse" />
      </div>
    </div>
  );
}

function EmptyBrief({ firstName }: { firstName: string }) {
  return (
    <div className="space-y-8">
      <div className="hero-mesh relative overflow-hidden rounded-3xl p-8 md:p-10 shadow-elevated">
        <div className="relative z-10 max-w-lg">
          <div className="flex items-center gap-3">
            <span className="flex items-center justify-center w-9 h-9 rounded-2xl bg-white/15 ring-1 ring-white/25">
              <Sparkles className="w-5 h-5 text-white" />
            </span>
            <p className="text-sm font-semibold text-white">Sage</p>
          </div>
          <h1 className="mt-6 text-2xl md:text-[28px] font-semibold leading-snug"
            style={{ color: '#fff', WebkitTextFillColor: '#fff' }}>
            {firstName ? `${firstName}, ` : ''}I&apos;m ready to brief you every morning.
          </h1>
          <p className="mt-3 text-white/80 leading-relaxed">
            Connect your sales and inventory and I&apos;ll read them overnight — then hand you the one call that
            matters, in dirhams, before your first coffee.
          </p>
          <Link href="/imports" className="inline-flex items-center gap-1.5 rounded-full bg-white px-5 py-2.5 mt-6 text-sm font-semibold text-teal-800 hover:bg-white/90 transition">
            Import your data <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>
    </div>
  );
}
