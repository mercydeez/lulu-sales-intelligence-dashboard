'use client';

/**
 * Sage Copilot — the dedicated AI-first surface (Phase 4, §3.4).
 *
 * The proactive feed IS the page: it renders the caller's server-configured
 * homepage zones through the same open widget registry as `/today` (zero
 * duplication — one config, one registry, two surfaces). On top it adds the
 * persona header (the first consumer of `ai_context`) and an embedded ask box
 * whose question hands off to the existing, tested chat panel via `openChat` —
 * no chat-thread re-implementation here.
 *
 * Any role can open the URL: the feed is server-scoped, so a store manager
 * simply sees their store's copilot. No client gating.
 */
import { useState } from 'react';
import { useExperience } from '@/contexts/ExperienceContext';
import { useAI } from '@/components/AIProvider';
import { resolveWidget } from '@/components/copilot/registry';
import { Button, ErrorState, SkeletonCard, Stagger, RevealItem } from '@/components/ui';
import { Sparkles, Send, MapPin } from 'lucide-react';
// Side-effect import: the feed widgets register before zones resolve.
import '@/components/copilot/feedWidgets';

const white = (o = 1): React.CSSProperties =>
  ({ color: `rgba(255,255,255,${o})`, WebkitTextFillColor: `rgba(255,255,255,${o})` });

const FOCUS_LABELS: Record<string, string> = {
  revenue: 'Revenue', profit: 'Profit', risks: 'Risks', growth: 'Growth',
  stockouts: 'Stockouts', today_sales: "Today's sales", reorders: 'Reorders',
  store_comparison: 'Store comparison', approvals: 'Approvals', wow_movement: 'WoW movement',
  po_queue: 'PO queue', stock_pressure: 'Stock pressure', overstock: 'Overstock',
};

// Grounded starter questions — they work for every role because the backend
// scopes every answer to the caller's stores.
const SUGGESTED_PROMPTS = [
  'What changed this week?',
  'Where am I losing money right now?',
  'What should I do first today?',
];

export default function CopilotPage() {
  const { config, loading } = useExperience();
  const { openChat } = useAI();
  const [question, setQuestion] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  const ask = (prompt: string) => {
    const q = prompt.trim();
    if (!q) return;
    setQuestion('');
    openChat(q); // the conversation continues in the existing panel
  };

  return (
    <main className="min-h-screen px-4 md:px-8 py-6 md:py-10">
      <div className="max-w-3xl mx-auto">
        {loading ? (
          <div className="space-y-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
        ) : !config ? (
          <ErrorState title="Couldn't load Sage Copilot" description="Your role experience is unavailable."
            onRetry={() => setReloadKey((k) => k + 1)} />
        ) : (
          <Stagger key={reloadKey} className="space-y-6">
            {/* Persona header — the first ai_context consumer (scope + focus). */}
            <RevealItem>
              <section className="hero-mesh relative overflow-hidden rounded-3xl p-6 md:p-8 shadow-elevated">
                <div className="relative z-10">
                  <div className="flex items-center gap-2.5">
                    <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-white/15 ring-1 ring-white/25">
                      <Sparkles className="w-4 h-4 text-white" />
                    </span>
                    <div className="leading-tight">
                      <p className="text-sm font-semibold" style={white()}>{config.persona.name}</p>
                      <p className="text-[11px]" style={white(0.7)}>{config.persona.title}</p>
                    </div>
                  </div>
                  <h1 className="mt-5 text-xl md:text-2xl font-semibold leading-snug max-w-[46ch]" style={white()}>
                    {config.persona.greeting}
                  </h1>
                  {config.ai_context && (
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 ring-1 ring-white/25 px-3 py-1 text-xs font-medium" style={white()}>
                        <MapPin className="w-3.5 h-3.5" aria-hidden /> {config.ai_context.scope}
                      </span>
                      {config.ai_context.focus.map((f) => (
                        <span key={f} className="inline-flex items-center rounded-full bg-white/10 ring-1 ring-white/20 px-2.5 py-1 text-[11px]" style={white(0.85)}>
                          {FOCUS_LABELS[f] ?? f}
                        </span>
                      ))}
                    </div>
                  )}
                  {/* Embedded ask box — hands off to the tested chat panel. */}
                  <form className="mt-5 flex items-center gap-2"
                    onSubmit={(e) => { e.preventDefault(); ask(question); }}>
                    <input
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      placeholder={`Ask ${config.persona.name ?? 'Sage'} anything about your business…`}
                      aria-label="Ask Sage a question"
                      className="flex-1 min-w-0 rounded-xl bg-white/15 ring-1 ring-white/25 px-4 py-2.5 text-sm text-white placeholder:text-white/60 outline-none focus-visible:ring-2 focus-visible:ring-white/60"
                    />
                    <Button type="submit" size="sm" variant="secondary" disabled={!question.trim()} aria-label="Send question">
                      <Send className="w-4 h-4" />
                    </Button>
                  </form>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {SUGGESTED_PROMPTS.map((p) => (
                      <button key={p} type="button" onClick={() => ask(p)}
                        className="rounded-full bg-white/10 ring-1 ring-white/20 px-3 py-1.5 text-xs hover:bg-white/20 transition"
                        style={white(0.85)}>
                        {p}
                      </button>
                    ))}
                  </div>
                </div>
              </section>
            </RevealItem>

            {/* The proactive feed: the caller's configured zones, minus the
                verdict hero (this page has its own persona header above). */}
            {(config.homepage?.zones ?? config.zones)
              .filter((z) => z.type !== 'verdict' && z.type !== 'briefing_hero')
              .map((zone, i) => {
                const Zone = resolveWidget(zone.type);
                if (!Zone) return null;
                return (
                  <RevealItem key={`${zone.type}-${i}`}>
                    <Zone config={config} spec={zone} />
                  </RevealItem>
                );
              })}

            <p className="text-xs text-ink-muted flex items-center gap-1.5 pt-2">
              <Sparkles className="w-3.5 h-3.5 text-teal-500" />
              Every figure above comes from your live data — Sage never invents a number.
            </p>
          </Stagger>
        )}
      </div>
    </main>
  );
}
