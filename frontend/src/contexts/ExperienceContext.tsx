'use client';

/**
 * Role Experience Engine (blueprint Wave 1) — client side.
 * Fetches the caller's server-driven experience config (/api/experience):
 * persona pack, homepage zones, KPI descriptors, nav manifest, decision scope.
 * Surfaces (Sidebar, /today, ChatBot) render from this config so a new role is
 * added by configuration, not new pages. Fails open: a fetch error yields
 * config=null and every surface falls back to today's default behavior.
 */
import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { apiGet } from '@/lib/apiClient';

export interface PersonaPack {
  name: string; title: string; tagline: string; greeting: string;
  voice: string[];
  // NOTE: the persona's system-prompt fragment is intentionally NOT part of the
  // client payload — it is server-only (assembled into Sage's prompt in the
  // backend). Never add it here.
}
export interface KpiDescriptor {
  key: string; label: string;
  source: 'kpis' | 'decisions' | 'inventory';
  field: string;
  format: 'aed' | 'units' | 'int' | 'trend';
}
export interface NavManifestItem {
  key: string; tKey: string; label: string; href: string; icon: string;
}
export interface ZoneSpec { type: string; props?: Record<string, unknown> }

// ── Experience API v2 (Sage Copilot) ──────────────────────────────────────
/** Which Sage shell the frontend renders. `copilot` and `panel` both use the
 *  panel today; the dedicated copilot surface lands in a later phase. */
export type AssistantMode = 'panel' | 'copilot' | 'hidden';
export interface QuickAction { key: string; label: string; href: string; icon?: string }
/** Rendering hints only — the server still authorizes every AI call. */
export interface Capabilities { ai_chat: boolean; voice: boolean }
/** Display/routing metadata only — never prompt text. */
export interface AiContext { focus: string[]; scope: string }
export interface HomepageSpec { layout: string; zones: ZoneSpec[] }

export interface ExperienceConfig {
  version?: number;
  key: string; role: string; home: string;
  decision_scope: 'chain' | 'region' | 'store';
  persona: PersonaPack;
  // v1 zone list (still emitted); v2 wraps it in `homepage`. Read `homepage.zones`
  // with a fallback to `zones` so both old and new payloads render.
  zones: ZoneSpec[];
  homepage?: HomepageSpec;
  kpis: KpiDescriptor[];
  nav: NavManifestItem[] | null;
  assistant_mode?: AssistantMode;
  quick_actions?: QuickAction[];
  ai_context?: AiContext;
  capabilities?: Capabilities;
  notifications?: Record<string, unknown>;
  context?: { accessible_store_count: number };
}

interface ExperienceState { config: ExperienceConfig | null; loading: boolean }

const ExperienceContext = createContext<ExperienceState>({ config: null, loading: true });

export function ExperienceProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth();
  const [state, setState] = useState<ExperienceState>({ config: null, loading: true });

  useEffect(() => {
    if (!isAuthenticated) { setState({ config: null, loading: false }); return; }
    let active = true;
    const timers: ReturnType<typeof setTimeout>[] = [];
    setState((s) => ({ ...s, loading: true }));
    // Retry with backoff: the page-load burst can trip the per-IP rate limit,
    // and a single failed fetch must not lock every surface into the fallback
    // experience (e.g. the full built-in sidebar instead of the curated nav).
    const attempt = (retriesLeft: number) => {
      apiGet<ExperienceConfig>('/api/experience')
        .then((cfg) => { if (active) setState({ config: cfg, loading: false }); })
        .catch(() => {
          if (!active) return;
          if (retriesLeft > 0) {
            timers.push(setTimeout(() => attempt(retriesLeft - 1), (4 - retriesLeft) * 1500));
          } else {
            setState({ config: null, loading: false });
          }
        });
    };
    attempt(3);
    return () => { active = false; timers.forEach(clearTimeout); };
    // Re-resolve when the signed-in user changes (role switch = new experience).
  }, [isAuthenticated, user?.email, user?.role]);

  return <ExperienceContext.Provider value={state}>{children}</ExperienceContext.Provider>;
}

export function useExperience(): ExperienceState {
  return useContext(ExperienceContext);
}
