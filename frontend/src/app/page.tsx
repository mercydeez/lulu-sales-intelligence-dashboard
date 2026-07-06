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
import { Reveal, ScrollReveal, Stagger, RevealItem } from '@/components/ui';

export default function Home() {
  const { hasRole, authFetch } = useAuth();
  const { t } = useLanguage();

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
              <span className="text-coral-500">🔄</span>
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
      </Stagger>
    </main>
  );
}
