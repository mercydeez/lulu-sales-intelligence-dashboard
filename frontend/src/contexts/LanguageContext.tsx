'use client';

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';
import { en, ar } from '@/locales';

export type Lang = 'en' | 'ar';
export type Dir = 'ltr' | 'rtl';

type Dict = Record<string, string>;

// Translations live in per-domain modules under src/locales/ (E4-4 i18n
// split) — add keys there under your own namespace, in BOTH dicts. Data/values
// stay untranslated. This context only owns the mechanism: lang state, <html>
// lang/dir reflection, persistence, and `t()`.
const DICTS: Record<Lang, Dict> = { en, ar };

interface LanguageContextValue {
  lang: Lang;
  dir: Dir;
  t: (key: string) => string;
  setLang: (lang: Lang) => void;
  toggleLang: () => void;
}

const LanguageContext = createContext<LanguageContextValue | undefined>(undefined);

export function LanguageProvider({ children }: { children: ReactNode }) {
  // Initialise from the persisted choice so the first client render already
  // matches the <html dir> set by the pre-paint script in layout.tsx — no
  // EN/AR flash and no "English text with an RTL sidebar" mismatch. The window
  // guard keeps SSR on the 'en' default; the authenticated UI is client-rendered
  // (auth-gated), so this lazy initialiser does not cause a hydration mismatch.
  const [lang, setLangState] = useState<Lang>(() => {
    if (typeof window !== 'undefined') {
      const saved = window.localStorage.getItem('lang');
      if (saved === 'en' || saved === 'ar') return saved;
    }
    return 'en';
  });

  // Reflect language + direction on <html> and persist.
  useEffect(() => {
    const dir: Dir = lang === 'ar' ? 'rtl' : 'ltr';
    if (typeof document !== 'undefined') {
      document.documentElement.lang = lang;
      document.documentElement.dir = dir;
    }
    if (typeof window !== 'undefined') window.localStorage.setItem('lang', lang);
  }, [lang]);

  const setLang = useCallback((l: Lang) => setLangState(l), []);
  const toggleLang = useCallback(() => setLangState((l) => (l === 'en' ? 'ar' : 'en')), []);
  const t = useCallback((key: string) => DICTS[lang][key] ?? en[key] ?? key, [lang]);

  const dir: Dir = lang === 'ar' ? 'rtl' : 'ltr';

  return (
    <LanguageContext.Provider value={{ lang, dir, t, setLang, toggleLang }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    // Safe fallback so components don't crash if rendered outside the provider.
    return {
      lang: 'en',
      dir: 'ltr',
      t: (key: string) => en[key] ?? key,
      setLang: () => {},
      toggleLang: () => {},
    };
  }
  return ctx;
}
