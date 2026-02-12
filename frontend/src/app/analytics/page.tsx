'use client';

import React, { useState, useEffect } from 'react';
import { 
  BarChart3, TrendingUp, TrendingDown, Target, Activity,
  Calendar, Download, RefreshCw, Store, Package, Users,
  ArrowUpRight, ArrowDownRight, Percent, DollarSign, ShoppingCart,
  FileText
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  ComposedChart, Scatter
} from 'recharts';
import { exportAnalyticsPDF } from '@/lib/pdfExport';

const COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899'];

interface SalesData {
  date: string;
  sales: number;
  transactions: number;
  avgBasket: number;
}

interface CategoryData {
  category: string;
  sales: number;
  growth: number;
  percentage: number;
}

interface StorePerformance {
  store_id: number;
  store_name: string;
  location: string;
  sales: number;
  transactions: number;
  avgBasket: number;
  growth: number;
}

interface HourlyTrend {
  hour: string;
  sales: number;
  footfall: number;
}

export default function AnalyticsPage() {
  const { user, authFetch, hasPermission } = useAuth();
  const [loading, setLoading] = useState(true);
  const [dateRange, setDateRange] = useState('7d');
  const [refreshing, setRefreshing] = useState(false);
  
  const [salesData, setSalesData] = useState<SalesData[]>([]);
  const [categoryData, setCategoryData] = useState<CategoryData[]>([]);
  const [storePerformance, setStorePerformance] = useState<StorePerformance[]>([]);
  const [hourlyTrend, setHourlyTrend] = useState<HourlyTrend[]>([]);
  
  const [kpis, setKpis] = useState({
    totalSales: 0,
    totalTransactions: 0,
    avgBasketSize: 0,
    conversionRate: 0,
    salesGrowth: 0,
    topCategory: ''
  });

  useEffect(() => {
    fetchAnalyticsData();
  }, [dateRange]);

  const fetchAnalyticsData = async () => {
    setLoading(true);
    try {
      // Try to fetch from API
      const [salesRes, kpisRes] = await Promise.all([
        authFetch(`/api/analytics/sales-trend?range=${dateRange}`),
        authFetch('/api/kpis'),
      ]);

      if (kpisRes.ok) {
        const kpisData = await kpisRes.json();
        setKpis({
          totalSales: kpisData.total_sales_today || 0,
          totalTransactions: kpisData.total_streaming_records || 0,
          avgBasketSize: kpisData.average_daily_sales || 0,
          conversionRate: 68.5,
          salesGrowth: 12.4,
          topCategory: 'Dairy'
        });
      }

      // Generate enhanced mock data for visualization
      generateMockData();
      
    } catch (error) {
      console.error('Failed to fetch analytics data:', error);
      generateMockData();
    } finally {
      setLoading(false);
    }
  };

  const generateMockData = () => {
    // Sales trend data
    const days = dateRange === '7d' ? 7 : dateRange === '30d' ? 30 : 90;
    const salesTrend: SalesData[] = [];
    let baseValue = 45000;
    
    for (let i = days; i >= 0; i--) {
      const date = new Date();
      date.setDate(date.getDate() - i);
      const variance = Math.random() * 10000 - 5000;
      const dayOfWeek = date.getDay();
      const weekendBoost = (dayOfWeek === 0 || dayOfWeek === 6) ? 8000 : 0;
      
      salesTrend.push({
        date: date.toLocaleDateString('en-AE', { month: 'short', day: 'numeric' }),
        sales: Math.round(baseValue + variance + weekendBoost),
        transactions: Math.round(800 + Math.random() * 400),
        avgBasket: Math.round(45 + Math.random() * 20)
      });
    }
    setSalesData(salesTrend);

    // Category data
    const categories: CategoryData[] = [
      { category: 'Dairy', sales: 285000, growth: 15.2, percentage: 22 },
      { category: 'Beverages', sales: 215000, growth: 8.5, percentage: 17 },
      { category: 'Bakery', sales: 178000, growth: -2.1, percentage: 14 },
      { category: 'Fruits', sales: 156000, growth: 12.8, percentage: 12 },
      { category: 'Vegetables', sales: 142000, growth: 5.4, percentage: 11 },
      { category: 'Meat', sales: 125000, growth: 18.3, percentage: 10 },
      { category: 'Frozen Foods', sales: 98000, growth: 22.1, percentage: 8 },
      { category: 'Household', sales: 75000, growth: 3.2, percentage: 6 }
    ];
    setCategoryData(categories);

    // Store performance
    const stores: StorePerformance[] = [
      { store_id: 1, store_name: 'Al Barsha', location: 'Dubai', sales: 156000, transactions: 2840, avgBasket: 55, growth: 12.5 },
      { store_id: 2, store_name: 'Deira City Centre', location: 'Dubai', sales: 142000, transactions: 2650, avgBasket: 54, growth: 8.2 },
      { store_id: 3, store_name: 'Karama', location: 'Dubai', sales: 128000, transactions: 2450, avgBasket: 52, growth: 15.8 },
      { store_id: 4, store_name: 'Mushrif Mall', location: 'Abu Dhabi', sales: 135000, transactions: 2520, avgBasket: 54, growth: 10.4 },
      { store_id: 5, store_name: 'Al Wahda', location: 'Abu Dhabi', sales: 118000, transactions: 2180, avgBasket: 54, growth: -2.3 },
      { store_id: 6, store_name: 'Khalidiyah', location: 'Abu Dhabi', sales: 98000, transactions: 1850, avgBasket: 53, growth: 6.7 },
      { store_id: 7, store_name: 'Sharjah City Centre', location: 'Sharjah', sales: 112000, transactions: 2100, avgBasket: 53, growth: 18.2 },
      { store_id: 8, store_name: 'Al Nahda', location: 'Sharjah', sales: 95000, transactions: 1780, avgBasket: 53, growth: 4.5 }
    ];
    setStorePerformance(stores);

    // Hourly trend
    const hourly: HourlyTrend[] = [];
    for (let h = 8; h <= 22; h++) {
      const peakHours = (h >= 10 && h <= 13) || (h >= 18 && h <= 21);
      const baseSales = peakHours ? 8000 : 4000;
      hourly.push({
        hour: `${h}:00`,
        sales: Math.round(baseSales + Math.random() * 2000),
        footfall: Math.round((baseSales / 50) + Math.random() * 40)
      });
    }
    setHourlyTrend(hourly);

    // Update KPIs with calculated totals
    const totalSales = salesTrend.reduce((acc, d) => acc + d.sales, 0);
    const totalTrans = salesTrend.reduce((acc, d) => acc + d.transactions, 0);
    setKpis(prev => ({
      ...prev,
      totalSales,
      totalTransactions: totalTrans,
      avgBasketSize: Math.round(totalSales / totalTrans)
    }));
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchAnalyticsData();
    setRefreshing(false);
  };

  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportAnalyticsPDF(
        kpis,
        salesData.map(d => ({ date: d.date, sales: d.sales, transactions: d.transactions })),
        categoryData.map(c => ({ category: c.category, sales: c.sales, percentage: c.percentage })),
        dateRange
      );
    } catch (error) {
      console.error('PDF export failed:', error);
      // Fallback to CSV if PDF fails
      const headers = ['Date', 'Sales', 'Transactions', 'Avg Basket'];
      const rows = salesData.map(d => [d.date, d.sales, d.transactions, d.avgBasket]);
      const csvContent = [headers, ...rows].map(row => row.join(',')).join('\n');
      
      const blob = new Blob([csvContent], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `analytics_${dateRange}_${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  const formatCurrency = (value: number) => {
    if (value >= 1000000) return `AED ${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `AED ${(value / 1000).toFixed(0)}K`;
    return `AED ${value}`;
  };

  const formatNumber = (value: number) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return value.toString();
  };

  if (loading) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-7xl mx-auto flex items-center justify-center h-[60vh]">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500 mx-auto mb-4"></div>
            <p className="text-slate-400">Loading analytics...</p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        {/* Page Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-white flex items-center gap-3">
              <BarChart3 className="w-8 h-8 text-cyan-500" />
              Analytics Dashboard
            </h1>
            <p className="mt-2 text-slate-400">
              Deep insights into sales performance and trends
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Date Range */}
            <select
              value={dateRange}
              onChange={(e) => setDateRange(e.target.value)}
              className="px-4 py-2 rounded-lg border border-slate-600 bg-slate-800 text-white"
            >
              <option value="7d">Last 7 Days</option>
              <option value="30d">Last 30 Days</option>
              <option value="90d">Last 90 Days</option>
            </select>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="p-2 rounded-lg bg-slate-800 border border-slate-600 text-white hover:bg-slate-700"
            >
              <RefreshCw className={`w-5 h-5 ${refreshing ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={handleExport}
              disabled={exporting}
              className="flex items-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {exporting ? (
                <>
                  <RefreshCw className="w-5 h-5 animate-spin" />
                  Exporting...
                </>
              ) : (
                <>
                  <Download className="w-5 h-5" />
                  Export PDF
                </>
              )}
            </button>
          </div>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          <div className="glass rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-slate-400">Total Sales</p>
              <DollarSign className="w-5 h-5 text-green-500" />
            </div>
            <p className="text-2xl font-bold text-white">{formatCurrency(kpis.totalSales)}</p>
            <div className="flex items-center gap-1 mt-1">
              <ArrowUpRight className="w-4 h-4 text-green-500" />
              <span className="text-sm text-green-500">+{kpis.salesGrowth}%</span>
            </div>
          </div>

          <div className="glass rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-slate-400">Transactions</p>
              <ShoppingCart className="w-5 h-5 text-blue-500" />
            </div>
            <p className="text-2xl font-bold text-white">{formatNumber(kpis.totalTransactions)}</p>
            <div className="flex items-center gap-1 mt-1">
              <ArrowUpRight className="w-4 h-4 text-green-500" />
              <span className="text-sm text-green-500">+8.2%</span>
            </div>
          </div>

          <div className="glass rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-slate-400">Avg Basket</p>
              <Package className="w-5 h-5 text-purple-500" />
            </div>
            <p className="text-2xl font-bold text-white">AED {kpis.avgBasketSize}</p>
            <div className="flex items-center gap-1 mt-1">
              <ArrowUpRight className="w-4 h-4 text-green-500" />
              <span className="text-sm text-green-500">+3.5%</span>
            </div>
          </div>

          <div className="glass rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-slate-400">Conversion</p>
              <Target className="w-5 h-5 text-orange-500" />
            </div>
            <p className="text-2xl font-bold text-white">{kpis.conversionRate}%</p>
            <div className="flex items-center gap-1 mt-1">
              <ArrowUpRight className="w-4 h-4 text-green-500" />
              <span className="text-sm text-green-500">+2.1%</span>
            </div>
          </div>

          <div className="glass rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-slate-400">Top Category</p>
              <TrendingUp className="w-5 h-5 text-cyan-500" />
            </div>
            <p className="text-2xl font-bold text-white">{kpis.topCategory}</p>
            <p className="text-sm text-slate-400 mt-1">22% of sales</p>
          </div>

          <div className="glass rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-slate-400">Active Stores</p>
              <Store className="w-5 h-5 text-red-500" />
            </div>
            <p className="text-2xl font-bold text-white">10</p>
            <p className="text-sm text-green-500 mt-1">All operational</p>
          </div>
        </div>

        {/* Charts Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          {/* Sales Trend Chart */}
          <div className="glass rounded-xl p-6">
            <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <Activity className="w-5 h-5 text-cyan-500" />
              Sales Trend
            </h3>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={salesData}>
                <defs>
                  <linearGradient id="salesGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} tickFormatter={(v) => `${(v/1000).toFixed(0)}K`} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                  labelStyle={{ color: '#f8fafc' }}
                  formatter={(value: number) => [formatCurrency(value), 'Sales']}
                />
                <Area type="monotone" dataKey="sales" stroke="#06b6d4" fill="url(#salesGradient)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Category Distribution */}
          <div className="glass rounded-xl p-6">
            <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <Package className="w-5 h-5 text-purple-500" />
              Category Distribution
            </h3>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={categoryData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={2}
                  dataKey="percentage"
                  nameKey="category"
                  label={({ category, percentage }) => `${category}: ${percentage}%`}
                >
                  {categoryData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                  formatter={(value: number, name: string, props: any) => [
                    formatCurrency(props.payload.sales), 
                    props.payload.category
                  ]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Hourly Sales Pattern */}
          <div className="glass rounded-xl p-6">
            <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <Calendar className="w-5 h-5 text-orange-500" />
              Hourly Sales Pattern
            </h3>
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={hourlyTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="hour" stroke="#94a3b8" fontSize={12} />
                <YAxis yAxisId="left" stroke="#94a3b8" fontSize={12} tickFormatter={(v) => `${(v/1000).toFixed(0)}K`} />
                <YAxis yAxisId="right" orientation="right" stroke="#94a3b8" fontSize={12} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                  labelStyle={{ color: '#f8fafc' }}
                />
                <Bar yAxisId="left" dataKey="sales" fill="#f97316" radius={[4, 4, 0, 0]} />
                <Line yAxisId="right" type="monotone" dataKey="footfall" stroke="#22c55e" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* Category Growth */}
          <div className="glass rounded-xl p-6">
            <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-green-500" />
              Category Growth
            </h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={categoryData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis type="number" stroke="#94a3b8" fontSize={12} domain={[-10, 30]} tickFormatter={(v) => `${v}%`} />
                <YAxis type="category" dataKey="category" stroke="#94a3b8" fontSize={12} width={80} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                  formatter={(value: number) => [`${value.toFixed(1)}%`, 'Growth']}
                />
                <Bar dataKey="growth" radius={[0, 4, 4, 0]}>
                  {categoryData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.growth >= 0 ? '#22c55e' : '#ef4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Store Performance Table */}
        <div className="glass rounded-xl p-6">
          <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <Store className="w-5 h-5 text-red-500" />
            Store Performance
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left py-3 px-4 text-sm font-medium text-slate-400">Store</th>
                  <th className="text-left py-3 px-4 text-sm font-medium text-slate-400">Location</th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-slate-400">Sales</th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-slate-400">Transactions</th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-slate-400">Avg Basket</th>
                  <th className="text-right py-3 px-4 text-sm font-medium text-slate-400">Growth</th>
                </tr>
              </thead>
              <tbody>
                {storePerformance.map((store, index) => (
                  <tr key={store.store_id} className="border-b border-slate-700/50 hover:bg-slate-800/50">
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-red-500 to-red-600 flex items-center justify-center text-white font-bold text-sm">
                          {index + 1}
                        </div>
                        <span className="font-medium text-white">{store.store_name}</span>
                      </div>
                    </td>
                    <td className="py-3 px-4 text-slate-400">{store.location}</td>
                    <td className="py-3 px-4 text-right font-medium text-white">{formatCurrency(store.sales)}</td>
                    <td className="py-3 px-4 text-right text-slate-300">{store.transactions.toLocaleString()}</td>
                    <td className="py-3 px-4 text-right text-slate-300">AED {store.avgBasket}</td>
                    <td className="py-3 px-4 text-right">
                      <span className={`flex items-center justify-end gap-1 ${store.growth >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                        {store.growth >= 0 ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                        {Math.abs(store.growth).toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </main>
  );
}
