'use client';

import { createContext, useContext, useEffect, useState, ReactNode } from 'react';

type Theme = 'light' | 'dark';

interface ThemeCtx {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeCtx | null>(null);

function applyClass(t: Theme) {
  const el = document.documentElement;
  el.classList.remove('light', 'dark');
  el.classList.add(t);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Default 'light'; hydrated from localStorage on mount (the no-FOUC script in
  // layout.tsx has already set the <html> class before paint).
  const [theme, setThemeState] = useState<Theme>('light');

  useEffect(() => {
    try {
      const saved = localStorage.getItem('theme');
      if (saved === 'dark' || saved === 'light') setThemeState(saved);
    } catch { /* ignore */ }
  }, []);

  const setTheme = (t: Theme) => {
    setThemeState(t);
    applyClass(t);
    try { localStorage.setItem('theme', t); } catch { /* ignore */ }
  };

  const toggle = () => setTheme(theme === 'dark' ? 'light' : 'dark');

  return <ThemeContext.Provider value={{ theme, setTheme, toggle }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
