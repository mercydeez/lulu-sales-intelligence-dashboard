'use client';

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';

/**
 * Theme system (E4-2) — light / dark / system tri-state.
 *
 * The resolved theme is reflected as `html.light` / `html.dark`, which drives
 * every CSS channel variable in globals.css (and therefore Tailwind's
 * canvas/surface/ink/line tokens and the chart palette). A pre-paint script in
 * layout.tsx applies the same resolution before first paint so there is no
 * flash of the wrong theme; this context keeps it in sync at runtime and
 * follows OS-level changes live while preference is 'system'.
 */
export type ThemePref = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'theme';

const isPref = (v: unknown): v is ThemePref => v === 'light' || v === 'dark' || v === 'system';

const systemTheme = (): ResolvedTheme => {
  if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
};

const resolve = (pref: ThemePref): ResolvedTheme => (pref === 'system' ? systemTheme() : pref);

interface ThemeContextValue {
  /** The user's stored preference (may be 'system'). */
  theme: ThemePref;
  /** What is actually applied right now. */
  resolved: ResolvedTheme;
  setTheme: (pref: ThemePref) => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Initialise from the persisted choice so the first client render already
  // matches the html class set by the pre-paint script in layout.tsx — same
  // no-flash pattern as LanguageContext. Missing/invalid key = 'system'.
  const [theme, setThemeState] = useState<ThemePref>(() => {
    if (typeof window !== 'undefined') {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (isPref(saved)) return saved;
    }
    return 'system';
  });
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolve(theme));

  // Reflect the resolved theme on <html> and persist the preference.
  useEffect(() => {
    const next = resolve(theme);
    setResolved(next);
    if (typeof document !== 'undefined') {
      const cl = document.documentElement.classList;
      cl.remove('light', 'dark');
      cl.add(next);
    }
    if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  // While on 'system', follow OS appearance changes live.
  useEffect(() => {
    if (theme !== 'system' || typeof window === 'undefined') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      const next: ResolvedTheme = mq.matches ? 'dark' : 'light';
      setResolved(next);
      const cl = document.documentElement.classList;
      cl.remove('light', 'dark');
      cl.add(next);
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [theme]);

  const setTheme = useCallback((pref: ThemePref) => setThemeState(pref), []);

  return (
    <ThemeContext.Provider value={{ theme, resolved, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    // Safe fallback so components don't crash if rendered outside the provider.
    return { theme: 'system', resolved: 'light', setTheme: () => {} };
  }
  return ctx;
}
