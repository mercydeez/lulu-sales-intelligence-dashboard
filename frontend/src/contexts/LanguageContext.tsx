'use client';

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';

export type Lang = 'en' | 'ar';
export type Dir = 'ltr' | 'rtl';

type Dict = Record<string, string>;

// Scoped translations (3.8): nav + home/inventory/alerts headings & tabs.
// Data/values stay untranslated; this is an EN/AR + RTL shell pass, not full i18n.
const en: Dict = {
  'nav.dashboard': 'Dashboard',
  'nav.inventory': 'Inventory',
  'nav.promotions': 'Promotions',
  'nav.analytics': 'Analytics',
  'nav.forecastLab': 'Forecast Lab',
  'nav.employees': 'Employees',
  'nav.reports': 'Reports',
  'nav.alerts': 'Alerts',
  'nav.admin': 'Admin',
  'nav.monitoring': 'Monitoring',
  'nav.dataSources': 'Data Sources',
  'nav.navigation': 'Navigation',
  'lang.toggle': 'العربية',
  'home.executiveInsights': 'Executive Insights',
  'home.realTimeStream': 'Real-Time Stream',
  'home.filteredRegion': '(Filtered to your region)',
  'home.filteredStore': '(Filtered to your store)',
  'inventory.title': 'Inventory & Procurement',
  'inventory.description': 'Monitor stock levels, manage alerts, and handle procurement across all stores',
  'inventory.tab.inventory': 'Inventory',
  'inventory.tab.alerts': 'Alerts',
  'inventory.tab.procurement': 'Procurement',
  'alerts.title': 'Alerts & Tasks',
  'alerts.description': 'Monitor, acknowledge, and resolve operational alerts across all stores',
  'alerts.tab.all': 'All Alerts',
  'alerts.tab.tasks': 'My Tasks',
};

const ar: Dict = {
  'nav.dashboard': 'لوحة القيادة',
  'nav.inventory': 'المخزون',
  'nav.promotions': 'العروض',
  'nav.analytics': 'التحليلات',
  'nav.forecastLab': 'مختبر التنبؤ',
  'nav.employees': 'الموظفون',
  'nav.reports': 'التقارير',
  'nav.alerts': 'التنبيهات',
  'nav.admin': 'الإدارة',
  'nav.monitoring': 'المراقبة',
  'nav.dataSources': 'مصادر البيانات',
  'nav.navigation': 'التنقل',
  'lang.toggle': 'English',
  'home.executiveInsights': 'رؤى تنفيذية',
  'home.realTimeStream': 'البث الفوري',
  'home.filteredRegion': '(مُصفّى حسب منطقتك)',
  'home.filteredStore': '(مُصفّى حسب متجرك)',
  'inventory.title': 'المخزون والمشتريات',
  'inventory.description': 'راقب مستويات المخزون وأدِر التنبيهات وتعامل مع المشتريات عبر جميع المتاجر',
  'inventory.tab.inventory': 'المخزون',
  'inventory.tab.alerts': 'التنبيهات',
  'inventory.tab.procurement': 'المشتريات',
  'alerts.title': 'التنبيهات والمهام',
  'alerts.description': 'راقب التنبيهات التشغيلية وأقرّها وحلّها عبر جميع المتاجر',
  'alerts.tab.all': 'جميع التنبيهات',
  'alerts.tab.tasks': 'مهامي',
};

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
