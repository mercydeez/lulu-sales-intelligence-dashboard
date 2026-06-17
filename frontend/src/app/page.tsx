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
import { ROLE_DISPLAY_NAMES, UserRole } from '@/types/auth';
import { Store, TrendingUp, Package, Users, Calendar, MapPin, AlertTriangle, Bell, ShoppingCart } from 'lucide-react';
import Link from 'next/link';

export default function Home() {
  const { user, hasRole, hasPermission, authFetch } = useAuth();
  
  // Alert stats state
  const [alertStats, setAlertStats] = useState({
    outOfStock: 12,
    lowStock: 45,
    pendingOrders: 8,
    criticalAlerts: 5,
  });

  // Fetch alert stats
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

  // Role-based welcome message
  const getWelcomeMessage = () => {
    if (!user) return '';
    
    switch (user.role) {
      case 'super_admin':
        return 'Full access to all stores and analytics across UAE';
      case 'regional_manager':
        return `Managing ${user.accessible_regions?.join(', ')} region`;
      case 'store_manager':
        return `Managing ${user.accessible_stores?.length || 0} store(s)`;
      case 'analyst':
        return 'View-only access to assigned stores';
      default:
        return '';
    }
  };

  // Get accessible store count
  const storeCount = user?.role === 'super_admin' ? 10 : (user?.accessible_stores?.length || 0);

  return (
    <main className="min-h-screen p-4 md:p-8">
      {/* Header with User Info */}
      <header className="max-w-7xl mx-auto mb-8">
        <div className="relative overflow-hidden rounded-3xl sunset-gradient p-6 md:p-8 text-white shadow-sunset">
          {/* Decorative blobs */}
          <div className="blob w-72 h-72 bg-amber-300/40 -top-16 right-10 animate-blob" />
          <div className="blob w-60 h-60 bg-teal-300/30 -bottom-16 left-1/4 animate-blob" style={{ animationDelay: '4s' }} />

          <div className="relative z-10 flex items-center justify-between flex-wrap gap-4">
            <div>
              <div className="flex items-center gap-3 mb-2 flex-wrap">
                <h1 className="text-3xl md:text-4xl font-bold tracking-tight">Lulu Hypermarket UAE</h1>
                <span className="px-3 py-1 rounded-full text-xs font-semibold bg-white/20 backdrop-blur-sm ring-1 ring-white/30">
                  {ROLE_DISPLAY_NAMES[user?.role as UserRole] || user?.role}
                </span>
              </div>
              <p className="text-white/85">
                Welcome back, <span className="font-semibold">{user?.first_name}</span>! {getWelcomeMessage()}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <div className="rounded-2xl px-4 py-2 flex items-center gap-2 bg-white/15 backdrop-blur-sm ring-1 ring-white/25">
                <Store className="w-4 h-4" />
                <span className="text-sm font-medium">
                  {storeCount} {storeCount === 1 ? 'Store' : 'Stores'}
                </span>
              </div>
              <div className="rounded-2xl px-4 py-2 flex items-center gap-2 bg-white/15 backdrop-blur-sm ring-1 ring-white/25">
                <span className="relative flex h-3 w-3">
                  <span className="absolute inline-flex h-3 w-3 rounded-full bg-white/80 animate-ping" />
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-white" />
                </span>
                <span className="text-sm font-semibold">LIVE</span>
              </div>
            </div>
          </div>
        </div>

        {/* Quick Stats for Role */}
        {user?.role === 'super_admin' && (
          <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { icon: MapPin, label: 'Regions', value: '3', tint: 'bg-coral-100 text-coral-600' },
              { icon: Store, label: 'Total Stores', value: '10', tint: 'bg-violet-100 text-violet-600' },
              { icon: Package, label: 'Products', value: '50', tint: 'bg-teal-100 text-teal-600' },
              { icon: Users, label: 'Users', value: '3', tint: 'bg-amber-100 text-amber-600' },
            ].map(({ icon: Icon, label, value, tint }) => (
              <div key={label} className="glass card-pop rounded-2xl p-4 flex items-center gap-3">
                <div className={`p-2.5 rounded-xl ${tint}`}>
                  <Icon className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-xs text-ink-muted">{label}</p>
                  <p className="text-lg font-bold text-ink">{value}</p>
                </div>
              </div>
            ))}
          </div>
        )}

        {user?.role === 'regional_manager' && (
          <div className="mt-4 p-4 glass rounded-2xl">
            <p className="text-xs text-ink-muted mb-2">Your Region: {user.accessible_regions?.join(', ').toUpperCase()}</p>
            <div className="flex flex-wrap gap-2">
              {user.accessible_stores?.map(storeId => (
                <span key={storeId} className="px-3 py-1 rounded-full bg-violet-100 text-violet-600 text-xs font-medium border border-violet-200">
                  Store #{storeId}
                </span>
              ))}
            </div>
          </div>
        )}

        {user?.role === 'store_manager' && (
          <div className="mt-4 p-4 glass rounded-2xl">
            <p className="text-xs text-ink-muted mb-2">Your Store</p>
            <p className="text-lg font-semibold text-teal-600">Lulu Hypermarket Al Barsha, Dubai</p>
          </div>
        )}
      </header>

      <div className="max-w-7xl mx-auto space-y-8">
        {/* Alert KPI Section - Left side prominence */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            {
              href: '/inventory?tab=alerts', label: 'Critical Alerts', value: alertStats.criticalAlerts,
              hint: 'Require immediate action', icon: AlertTriangle,
              text: 'text-coral-600', tile: 'bg-coral-100 text-coral-600', ring: 'hover:border-coral-300',
            },
            {
              href: '/inventory?status=out_of_stock', label: 'Out of Stock', value: alertStats.outOfStock,
              hint: 'Items need restock', icon: Package,
              text: 'text-amber-600', tile: 'bg-amber-100 text-amber-600', ring: 'hover:border-amber-300',
            },
            {
              href: '/inventory?status=low_stock', label: 'Low Stock', value: alertStats.lowStock,
              hint: 'Below reorder level', icon: Bell,
              text: 'text-teal-600', tile: 'bg-teal-100 text-teal-600', ring: 'hover:border-teal-300',
            },
            {
              href: '/inventory?tab=procurement', label: 'Pending Orders', value: alertStats.pendingOrders,
              hint: 'Awaiting approval', icon: ShoppingCart,
              text: 'text-violet-600', tile: 'bg-violet-100 text-violet-600', ring: 'hover:border-violet-300',
            },
          ].map(({ href, label, value, hint, icon: Icon, text, tile, ring }) => (
            <Link
              key={label}
              href={href}
              className={`glass card-pop rounded-2xl p-4 border border-transparent ${ring} group cursor-pointer`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className={`text-xs uppercase tracking-wider font-semibold ${text}`}>{label}</p>
                  <p className={`text-3xl font-bold mt-1 ${text}`}>{value}</p>
                  <p className="text-xs text-ink-muted mt-1">{hint}</p>
                </div>
                <div className={`p-3 rounded-2xl ${tile} group-hover:scale-110 transition-transform`}>
                  <Icon className="w-7 h-7" />
                </div>
              </div>
            </Link>
          ))}
        </section>

        {/* KPI Cards - Auto-refresh every 30 seconds */}
        <section>
          <KPICards refreshInterval={30000} />
        </section>

        {/* Executive Charts Section - Full access for all roles */}
        <section>
          <h2 className="text-2xl font-bold text-ink mb-6 flex items-center gap-3">
            <span className="w-1.5 h-8 sunset-gradient rounded-full"></span>
            Executive Insights
            {user?.role !== 'super_admin' && (
              <span className="text-sm font-normal text-ink-muted ml-2">
                (Filtered to your {user?.role === 'regional_manager' ? 'region' : 'store'})
              </span>
            )}
          </h2>
          
          {/* Sales Trend with Forecast - Full Width */}
          <div className="mb-6">
            <SalesTrendChart days={30} />
          </div>

          {/* Live Stream Chart - Full Width */}
          <div className="mb-6">
            <LiveStreamChart />
          </div>

          {/* Charts Grid - Sales Distribution */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Store Distribution Pie Chart - Hide for store managers (only 1 store) */}
            {(hasRole(['super_admin', 'regional_manager'])) && (
              <StoreDistributionChart />
            )}
            
            {/* Category Breakdown Donut Chart */}
            <CategoryBreakdownChart />
          </div>

          {/* Returns Analysis Section */}
          <div className="mb-6">
            <h3 className="text-xl font-semibold text-ink mb-4 flex items-center gap-2">
              <span className="text-coral-500">🔄</span>
              Returns Analysis
            </h3>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Returns by Category Donut Chart */}
              <ReturnsByCategoryChart />
              
              {/* Live Returns Feed */}
              <ReturnsLiveFeed />
            </div>
          </div>

          {/* Top Items Bar Chart - Full Width */}
          <div className="mt-6">
            <TopItemsChart />
          </div>
        </section>
        
        {/* Live Table - SSE Real-time updates */}
        <section>
          <h2 className="text-2xl font-bold text-ink mb-6 flex items-center gap-3">
            <span className="w-1.5 h-8 sunset-cool rounded-full"></span>
            Real-Time Stream
          </h2>
          <LiveTable />
        </section>

        {/* Financial Section - Only for users with financial permission */}
        {hasPermission('can_view_financials') && (
          <section>
            <h2 className="text-2xl font-bold text-ink mb-6 flex items-center gap-3">
              <span className="w-1.5 h-8 sunset-warm rounded-full"></span>
              Financial Overview
              <span className="ml-2 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
                Restricted Access
              </span>
            </h2>
            <div className="glass rounded-2xl p-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="text-center">
                  <p className="text-ink-muted text-sm mb-1">Monthly Revenue</p>
                  <p className="text-3xl font-bold text-ink">AED 2.4M</p>
                  <p className="text-teal-600 text-sm font-medium">+12.5% vs last month</p>
                </div>
                <div className="text-center">
                  <p className="text-ink-muted text-sm mb-1">Gross Margin</p>
                  <p className="text-3xl font-bold text-ink">24.8%</p>
                  <p className="text-violet-600 text-sm font-medium">Target: 25%</p>
                </div>
                <div className="text-center">
                  <p className="text-ink-muted text-sm mb-1">Operating Costs</p>
                  <p className="text-3xl font-bold text-ink">AED 580K</p>
                  <p className="text-coral-600 text-sm font-medium">-3.2% optimized</p>
                </div>
              </div>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
