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
  voice: string[]; prompt_fragment: string;
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

export interface ExperienceConfig {
  key: string; role: string; home: string;
  decision_scope: 'chain' | 'region' | 'store';
  persona: PersonaPack;
  zones: ZoneSpec[];
  kpis: KpiDescriptor[];
  nav: NavManifestItem[] | null;
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
    setState((s) => ({ ...s, loading: true }));
    apiGet<ExperienceConfig>('/api/experience')
      .then((cfg) => { if (active) setState({ config: cfg, loading: false }); })
      .catch(() => { if (active) setState({ config: null, loading: false }); });
    return () => { active = false; };
    // Re-resolve when the signed-in user changes (role switch = new experience).
  }, [isAuthenticated, user?.email, user?.role]);

  return <ExperienceContext.Provider value={state}>{children}</ExperienceContext.Provider>;
}

export function useExperience(): ExperienceState {
  return useContext(ExperienceContext);
}
