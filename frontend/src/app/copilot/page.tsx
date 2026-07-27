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
import { Button, ErrorState, SkeletonCard, Stagger, RevealItem, HeroVerdict, onMesh } from '@/components/ui';
import { HomeTemplate } from '@/components/templates';
import { Sparkles, Send, MapPin } from 'lucide-react';
// Side-effect import: the feed widgets register before zones resolve.
import '@/components/copilot/feedWidgets';

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

  if (loading) {
    return (
      <HomeTemplate>
        <div className="space-y-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
      </HomeTemplate>
    );
  }
  if (!config) {
    return (
      <HomeTemplate>
        <div className="pt-6">
          <ErrorState title="Couldn't load Sage Copilot" description="Your role experience is unavailable."
            onRetry={() => setReloadKey((k) => k + 1)} />
        </div>
      </HomeTemplate>
    );
  }

  const zones = (config.homepage?.zones ?? config.zones)
    .filter((z) => z.type !== 'verdict' && z.type !== 'briefing_hero');

  return (
    <HomeTemplate
      hero={
        <RevealItem>
          {/* Persona header — the first ai_context consumer (scope + focus) —
              framed by the shared HeroVerdict grammar (DESIGN_SYSTEM §6.1); the
              ask box + suggested prompts ride in the CTA slot so they stay inside
              the same hero card as before. */}
          <HeroVerdict
            name={config.persona.name}
            title={config.persona.title}
            verdict={config.persona.greeting}
            chips={config.ai_context && (
              <>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 ring-1 ring-white/25 px-3 py-1 text-xs font-medium" style={onMesh()}>
                  <MapPin className="w-3.5 h-3.5" aria-hidden /> {config.ai_context.scope}
                </span>
                {config.ai_context.focus.map((f) => (
                  <span key={f} className="inline-flex items-center rounded-full bg-white/10 ring-1 ring-white/20 px-2.5 py-1 text-[11px]" style={onMesh(0.85)}>
                    {FOCUS_LABELS[f] ?? f}
                  </span>
                ))}
              </>
            )}
            cta={
              <div className="w-full space-y-3">
                {/* Embedded ask box — hands off to the tested chat panel. */}
                <form className="flex items-center gap-2"
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
                <div className="flex flex-wrap gap-2">
                  {SUGGESTED_PROMPTS.map((p) => (
                    <button key={p} type="button" onClick={() => ask(p)}
                      className="rounded-full bg-white/10 ring-1 ring-white/20 px-3 py-1.5 text-xs hover:bg-white/20 transition"
                      style={onMesh(0.85)}>
                      {p}
                    </button>
                  ))}
                </div>
              </div>
            }
          />
        </RevealItem>
      }
      footer={
        <p className="text-xs text-ink-muted flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-teal-500" />
          Every figure above comes from your live data — Sage never invents a number.
        </p>
      }
    >
      {/* The proactive feed: the caller's configured zones, minus the verdict
          hero (already rendered above via HeroVerdict). */}
      <Stagger key={reloadKey} className="space-y-6">
        {zones.map((zone, i) => {
          const Zone = resolveWidget(zone.type);
          if (!Zone) return null;
          return (
            <RevealItem key={`${zone.type}-${i}`}>
              <Zone config={config} spec={zone} />
            </RevealItem>
          );
        })}
      </Stagger>
    </HomeTemplate>
  );
}
