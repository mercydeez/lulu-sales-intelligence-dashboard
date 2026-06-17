'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import KPICards from '@/components/KPICards';
import LiveTable from '@/components/LiveTable';
import {
  SalesTrendChart,
  StoreDistributionChart,
  TopItemsChart,
  CategoryBreakdownChart,
  LiveStreamChart,
  ReturnsByCategoryChart,
  ReturnsLiveFeed
} from '@/components/charts';
import { HomeHero, AlertQuickLinks, FinancialOverview, AlertStats } from '@/components/home';

export default function Home() {
  const { hasRole, authFetch } = useAuth();

  const [alertStats, setAlertStats] = useState<AlertStats>({
    outOfStock: 12,
    lowStock: 45,
    pendingOrders: 8,
    criticalAlerts: 5,
  });

  useEffect(() => {
    const fetchAlertStats = async () => {
      try {
        const response = await authFetch('/api/inventory/summary');
        if (response.ok) {
          const data = await response.json();
          setAlertStats({
            outOfStock: data.out_of_stock_count || 12,
            lowStock: data.low_stock_count || 45,
            pendingOrders: data.pending_transfers || 8,
            criticalAlerts: data.out_of_stock_count || 5,
          });
        }
      } catch {
        // Use default alert stats on fetch failure
      }
    };
    fetchAlertStats();
  }, [authFetch]);

  return (
    <main className="min-h-screen p-4 md:p-8">
      <HomeHero />

      <div className="max-w-7xl mx-auto space-y-8">
        <AlertQuickLinks stats={alertStats} />

        <section>
          <KPICards refreshInterval={30000} />
        </section>

        <section>
          <h2 className="text-2xl font-bold text-ink mb-6 flex items-center gap-3">
            <span className="w-1.5 h-8 sunset-gradient rounded-full"></span>
            Executive Insights
            {!hasRole(['super_admin']) && (
              <span className="text-sm font-normal text-ink-muted ml-2">
                (Filtered to your {hasRole(['regional_manager']) ? 'region' : 'store'})
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
            {hasRole(['super_admin', 'regional_manager']) && <StoreDistributionChart />}
            <CategoryBreakdownChart />
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
            <TopItemsChart />
          </div>
        </section>

        <section>
          <h2 className="text-2xl font-bold text-ink mb-6 flex items-center gap-3">
            <span className="w-1.5 h-8 sunset-cool rounded-full"></span>
            Real-Time Stream
          </h2>
          <LiveTable />
        </section>

        <FinancialOverview />
      </div>
    </main>
  );
}
