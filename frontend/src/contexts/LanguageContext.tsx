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
  'nav.employees': 'Employees',
  'nav.reports': 'Reports',
  'nav.alerts': 'Alerts',
  'nav.admin': 'Admin',
  'nav.monitoring': 'Monitoring',
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
  'nav.employees': 'الموظفون',
  'nav.reports': 'التقارير',
  'nav.alerts': 'التنبيهات',
  'nav.admin': 'الإدارة',
  'nav.monitoring': 'المراقبة',
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
  const [lang, setLangState] = useState<Lang>('en');

  // Restore saved choice on mount.
  useEffect(() => {
    const saved = (typeof window !== 'undefined' && window.localStorage.getItem('lang')) as Lang | null;
    if (saved === 'en' || saved === 'ar') setLangState(saved);
  }, []);

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
