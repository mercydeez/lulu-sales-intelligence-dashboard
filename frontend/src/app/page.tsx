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
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <h1 className="text-4xl font-bold gradient-text">Lulu Hypermarket UAE</h1>
              <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
                user?.role === 'super_admin' ? 'bg-purple-500/20 text-purple-400 border border-purple-500/30' :
                user?.role === 'regional_manager' ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' :
                user?.role === 'store_manager' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                'bg-slate-500/20 text-slate-400 border border-slate-500/30'
              }`}>
                {ROLE_DISPLAY_NAMES[user?.role as UserRole] || user?.role}
              </span>
            </div>
            <p className="text-slate-400">
              Welcome back, <span className="text-white font-medium">{user?.first_name}</span>! {getWelcomeMessage()}
            </p>
          </div>
          <div className="flex items-center gap-4">
            {/* Access Level Badge */}
            <div className="glass rounded-xl px-4 py-2 flex items-center gap-3">
              <Store className="w-4 h-4 text-slate-400" />
              <span className="text-sm text-slate-300">
                {storeCount} {storeCount === 1 ? 'Store' : 'Stores'}
              </span>
            </div>
            <div className="glass rounded-xl px-4 py-2 flex items-center gap-3">
              <div className="relative">
                <span className="absolute inline-flex h-3 w-3 rounded-full bg-red-500 animate-pulse-glow"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
              </div>
              <span className="text-sm font-medium text-white">LIVE</span>
            </div>
          </div>
        </div>

        {/* Quick Stats for Role */}
        {user?.role === 'super_admin' && (
          <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="glass rounded-xl p-4 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-purple-500/20">
                <MapPin className="w-5 h-5 text-purple-400" />
              </div>
              <div>
                <p className="text-xs text-slate-400">Regions</p>
                <p className="text-lg font-bold text-white">3</p>
              </div>
            </div>
            <div className="glass rounded-xl p-4 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-cyan-500/20">
                <Store className="w-5 h-5 text-cyan-400" />
              </div>
              <div>
                <p className="text-xs text-slate-400">Total Stores</p>
                <p className="text-lg font-bold text-white">10</p>
              </div>
            </div>
            <div className="glass rounded-xl p-4 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-emerald-500/20">
                <Package className="w-5 h-5 text-emerald-400" />
              </div>
              <div>
                <p className="text-xs text-slate-400">Products</p>
                <p className="text-lg font-bold text-white">50</p>
              </div>
            </div>
            <div className="glass rounded-xl p-4 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-amber-500/20">
                <Users className="w-5 h-5 text-amber-400" />
              </div>
              <div>
                <p className="text-xs text-slate-400">Users</p>
                <p className="text-lg font-bold text-white">3</p>
              </div>
            </div>
          </div>
        )}

        {user?.role === 'regional_manager' && (
          <div className="mt-4 p-4 glass rounded-xl">
            <p className="text-xs text-slate-400 mb-2">Your Region: {user.accessible_regions?.join(', ').toUpperCase()}</p>
            <div className="flex flex-wrap gap-2">
              {user.accessible_stores?.map(storeId => (
                <span key={storeId} className="px-3 py-1 rounded-full bg-cyan-500/10 text-cyan-400 text-xs border border-cyan-500/20">
                  Store #{storeId}
                </span>
              ))}
            </div>
          </div>
        )}

        {user?.role === 'store_manager' && (
          <div className="mt-4 p-4 glass rounded-xl">
            <p className="text-xs text-slate-400 mb-2">Your Store</p>
            <p className="text-lg font-semibold text-emerald-400">Lulu Hypermarket Al Barsha, Dubai</p>
          </div>
        )}
      </header>

      <div className="max-w-7xl mx-auto space-y-8">
        {/* Alert KPI Section - Left side prominence */}
        <section className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          {/* Critical Alerts Card */}
          <Link href="/inventory?tab=alerts" className="glass rounded-xl p-4 border border-red-500/30 hover:border-red-500/60 transition-all group cursor-pointer">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-red-400 uppercase tracking-wider font-medium">Critical Alerts</p>
                <p className="text-3xl font-bold text-red-400 mt-1">{alertStats.criticalAlerts}</p>
                <p className="text-xs text-slate-400 mt-1">Require immediate action</p>
              </div>
              <div className="p-3 rounded-xl bg-red-500/20 group-hover:bg-red-500/30 transition-colors">
                <AlertTriangle className="w-8 h-8 text-red-400" />
              </div>
            </div>
          </Link>

          {/* Out of Stock Card */}
          <Link href="/inventory?status=out_of_stock" className="glass rounded-xl p-4 border border-orange-500/30 hover:border-orange-500/60 transition-all group cursor-pointer">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-orange-400 uppercase tracking-wider font-medium">Out of Stock</p>
                <p className="text-3xl font-bold text-orange-400 mt-1">{alertStats.outOfStock}</p>
                <p className="text-xs text-slate-400 mt-1">Items need restock</p>
              </div>
              <div className="p-3 rounded-xl bg-orange-500/20 group-hover:bg-orange-500/30 transition-colors">
                <Package className="w-8 h-8 text-orange-400" />
              </div>
            </div>
          </Link>

          {/* Low Stock Card */}
          <Link href="/inventory?status=low_stock" className="glass rounded-xl p-4 border border-yellow-500/30 hover:border-yellow-500/60 transition-all group cursor-pointer">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-yellow-400 uppercase tracking-wider font-medium">Low Stock</p>
                <p className="text-3xl font-bold text-yellow-400 mt-1">{alertStats.lowStock}</p>
                <p className="text-xs text-slate-400 mt-1">Below reorder level</p>
              </div>
              <div className="p-3 rounded-xl bg-yellow-500/20 group-hover:bg-yellow-500/30 transition-colors">
                <Bell className="w-8 h-8 text-yellow-400" />
              </div>
            </div>
          </Link>

          {/* Pending Orders Card */}
          <Link href="/inventory?tab=procurement" className="glass rounded-xl p-4 border border-purple-500/30 hover:border-purple-500/60 transition-all group cursor-pointer">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-purple-400 uppercase tracking-wider font-medium">Pending Orders</p>
                <p className="text-3xl font-bold text-purple-400 mt-1">{alertStats.pendingOrders}</p>
                <p className="text-xs text-slate-400 mt-1">Awaiting approval</p>
              </div>
              <div className="p-3 rounded-xl bg-purple-500/20 group-hover:bg-purple-500/30 transition-colors">
                <ShoppingCart className="w-8 h-8 text-purple-400" />
              </div>
            </div>
          </Link>
        </section>

        {/* KPI Cards - Auto-refresh every 30 seconds */}
        <section>
          <KPICards refreshInterval={30000} />
        </section>

        {/* Executive Charts Section - Full access for all roles */}
        <section>
          <h2 className="text-2xl font-bold text-white mb-6 flex items-center gap-3">
            <span className="w-1 h-8 bg-gradient-to-b from-cyan-400 to-purple-500 rounded-full"></span>
            Executive Insights
            {user?.role !== 'super_admin' && (
              <span className="text-sm font-normal text-slate-400 ml-2">
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
            <h3 className="text-xl font-semibold text-white mb-4 flex items-center gap-2">
              <span className="text-red-400">🔄</span>
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
          <h2 className="text-2xl font-bold text-white mb-6 flex items-center gap-3">
            <span className="w-1 h-8 bg-gradient-to-b from-emerald-400 to-cyan-500 rounded-full"></span>
            Real-Time Stream
          </h2>
          <LiveTable />
        </section>

        {/* Financial Section - Only for users with financial permission */}
        {hasPermission('can_view_financials') && (
          <section>
            <h2 className="text-2xl font-bold text-white mb-6 flex items-center gap-3">
              <span className="w-1 h-8 bg-gradient-to-b from-amber-400 to-orange-500 rounded-full"></span>
              Financial Overview
              <span className="ml-2 px-2 py-0.5 rounded text-xs bg-amber-500/20 text-amber-400">
                Restricted Access
              </span>
            </h2>
            <div className="glass rounded-2xl p-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="text-center">
                  <p className="text-slate-400 text-sm mb-1">Monthly Revenue</p>
                  <p className="text-3xl font-bold text-white">AED 2.4M</p>
                  <p className="text-emerald-400 text-sm">+12.5% vs last month</p>
                </div>
                <div className="text-center">
                  <p className="text-slate-400 text-sm mb-1">Gross Margin</p>
                  <p className="text-3xl font-bold text-white">24.8%</p>
                  <p className="text-cyan-400 text-sm">Target: 25%</p>
                </div>
                <div className="text-center">
                  <p className="text-slate-400 text-sm mb-1">Operating Costs</p>
                  <p className="text-3xl font-bold text-white">AED 580K</p>
                  <p className="text-amber-400 text-sm">-3.2% optimized</p>
                </div>
              </div>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
