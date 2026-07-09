'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import KPICards from '@/components/KPICards';
import RevenueProjectionCard from '@/components/RevenueProjectionCard';
import OnboardingChecklist from '@/components/OnboardingChecklist';
import ActionCenter from '@/components/ActionCenter';
import LiveTable from '@/components/LiveTable';
import {
  SalesTrendChart,
  LiveStreamChart,
  ReturnsByCategoryChart,
  ReturnsLiveFeed
} from '@/components/charts';
import { StoreDistributionPanel, CategoryDonut, TopItemsPanel } from '@/components/analytics';
import { HomeHero, AlertQuickLinks, FinancialOverview, AlertStats } from '@/components/home';
import SecurityPostureCard from '@/components/home/SecurityPostureCard';
import ExecutiveSummary from '@/components/home/ExecutiveSummary';
import SageFirstRun from '@/components/home/SageFirstRun';
import NpsPulse from '@/components/home/NpsPulse';
import { Reveal, ScrollReveal, Stagger, RevealItem } from '@/components/ui';
import { track } from '@/lib/telemetry';
import { RotateCcw } from 'lucide-react';

type Density = 'standard' | 'executive';

export default function Home() {
  const { hasRole, authFetch } = useAuth();
  const { t } = useLanguage();

  // Executive mode (E4-6): one number, one trend, one anomaly surface —
  // the analytics wall becomes drill-down. Persisted per browser.
  const [density, setDensity] = useState<Density>(() => {
    if (typeof window !== 'undefined') {
      const saved = window.localStorage.getItem('dashboard.density');
      if (saved === 'executive' || saved === 'standard') return saved;
    }
    return 'standard';
  });
  const setMode = (mode: Density) => {
    setDensity(mode);
    try { window.localStorage.setItem('dashboard.density', mode); } catch { /* private mode */ }
    track('exec_mode_toggled', { mode });
  };

  const [alertStats, setAlertStats] = useState<AlertStats>({
    outOfStock: 0,
    lowStock: 0,
    pendingOrders: 0,
    criticalAlerts: 0,
  });

  useEffect(() => {
    const fetchAlertStats = async () => {
      try {
        const [inventoryRes, alertsRes, approvalsRes] = await Promise.all([
          authFetch('/api/inventory/summary'),
          authFetch('/api/alerts/summary'),
          authFetch('/api/procurement/approvals'),
        ]);
        const inventory = inventoryRes.ok ? await inventoryRes.json() : null;
        const alerts = alertsRes.ok ? await alertsRes.json() : null;
        const approvals = approvalsRes.ok ? await approvalsRes.json() : null;
        setAlertStats({
          outOfStock: inventory?.out_of_stock_count ?? 0,
          lowStock: inventory?.low_stock_count ?? 0,
          pendingOrders: approvals?.count ?? 0,
          criticalAlerts: alerts?.critical_alerts ?? 0,
        });
      } catch {
        setAlertStats({ outOfStock: 0, lowStock: 0, pendingOrders: 0, criticalAlerts: 0 });
      }
    };
    fetchAlertStats();
  }, [authFetch]);

  return (
    <main className="min-h-screen p-4 md:p-8">
      <Reveal>
        <HomeHero />
      </Reveal>

      <Stagger className="max-w-7xl mx-auto space-y-8">
        {/* Density toggle (E4-6) — mirrors the language/theme segment pattern */}
        <RevealItem>
          <div className="flex justify-end">
            <div role="group" aria-label="Dashboard density" className="flex items-center rounded-lg border border-line overflow-hidden">
              {(['standard', 'executive'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setMode(mode)}
                  aria-pressed={density === mode}
                  className={`px-3 py-1.5 text-xs font-semibold capitalize transition-colors ${
                    density === mode ? 'bg-teal-600 text-white' : 'text-ink-muted hover:bg-surface-2'
                  }`}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>
        </RevealItem>

        {/* Sage first-run nudge (A1) — both densities, disappears once used */}
        <RevealItem>
          <SageFirstRun />
        </RevealItem>

        {/* Quarterly NPS pulse (Y6) — cadence-gated, shows rarely */}
        <RevealItem>
          <NpsPulse />
        </RevealItem>

        {density === 'executive' ? (
          <>
            {/* Executive view: one number, one trend, one anomaly surface */}
            <RevealItem>
              <ExecutiveSummary />
            </RevealItem>
            <RevealItem>
              <SalesTrendChart days={30} />
            </RevealItem>
            <RevealItem>
              <ActionCenter />
            </RevealItem>
            <RevealItem>
              <div className="text-center">
                <button
                  type="button"
                  onClick={() => setMode('standard')}
                  className="text-sm font-medium text-teal-700 hover:text-teal-600 dark:text-teal-300 transition-colors"
                >
                  Show the full dashboard →
                </button>
              </div>
            </RevealItem>
          </>
        ) : (
        <>
        <RevealItem>
          <AlertQuickLinks stats={alertStats} />
        </RevealItem>

        <RevealItem>
          <OnboardingChecklist />
        </RevealItem>

        <RevealItem>
          <ActionCenter />
        </RevealItem>

        <RevealItem>
          <KPICards refreshInterval={30000} />
        </RevealItem>

        {hasRole(['super_admin']) && (
          <RevealItem>
            <SecurityPostureCard />
          </RevealItem>
        )}

        <RevealItem>
          <RevenueProjectionCard />
        </RevealItem>

        <RevealItem>
          <h2 className="text-2xl font-bold text-ink mb-6 flex items-center gap-3">
            <span className="w-1.5 h-8 sunset-gradient rounded-full"></span>
            {t('home.executiveInsights')}
            {!hasRole(['super_admin']) && (
              <span className="text-sm font-normal text-ink-muted ms-2">
                {hasRole(['regional_manager']) ? t('home.filteredRegion') : t('home.filteredStore')}
              </span>
            )}
          </h2>

          <div className="mb-6">
            <SalesTrendChart days={30} />
          </div>

          <div className="mb-6">
            <LiveStreamChart />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {hasRole(['super_admin', 'regional_manager']) && <StoreDistributionPanel />}
            <CategoryDonut />
          </div>

          <div className="mb-6">
            <h3 className="text-xl font-semibold text-ink mb-4 flex items-center gap-2">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-rose-100 text-rose-700">
                <RotateCcw className="h-4 w-4" aria-hidden />
              </span>
              Returns Analysis
            </h3>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <ReturnsByCategoryChart />
              <ReturnsLiveFeed />
            </div>
          </div>

          <div className="mt-6">
            <TopItemsPanel />
          </div>
        </RevealItem>

        <ScrollReveal>
          <h2 className="text-2xl font-bold text-ink mb-6 flex items-center gap-3">
            <span className="w-1.5 h-8 sunset-cool rounded-full"></span>
            {t('home.realTimeStream')}
          </h2>
          <LiveTable />
        </ScrollReveal>

        <ScrollReveal>
          <FinancialOverview />
        </ScrollReveal>
        </>
        )}
      </Stagger>
    </main>
  );
}
