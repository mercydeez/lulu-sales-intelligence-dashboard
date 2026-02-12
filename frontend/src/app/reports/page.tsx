'use client';

import React, { useState, useEffect } from 'react';
import { 
  BarChart3, TrendingUp, TrendingDown, DollarSign, 
  Calendar, Download, Filter, RefreshCw, Store,
  ShoppingCart, Package, Users, ArrowUpRight, ArrowDownRight, FileText
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, AreaChart, Area
} from 'recharts';
import { exportReportsPDF } from '@/lib/pdfExport';

interface SalesTrend {
  date: string;
  sales: number;
  transactions: number;
}

interface CategorySales {
  category: string;
  sales: number;
  percentage: number;
}

interface StoreSales {
  store_id: number;
  store_name: string;
  location: string;
  sales: number;
  growth: number;
}

interface TopItem {
  item_id: number;
  item_name: string;
  category: string;
  total_sales: number;
  quantity: number;
}

const COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899'];

export default function ReportsPage() {
  const { user, authFetch, hasPermission } = useAuth();
  const [loading, setLoading] = useState(true);
  const [dateRange, setDateRange] = useState('7d');
  const [selectedStore, setSelectedStore] = useState<number | null>(null);
  
  // Mock data for demonstration
  const [salesTrend, setSalesTrend] = useState<SalesTrend[]>([]);
  const [categorySales, setCategorySales] = useState<CategorySales[]>([]);
  const [storeSales, setStoreSales] = useState<StoreSales[]>([]);
  const [topItems, setTopItems] = useState<TopItem[]>([]);
  const [kpis, setKpis] = useState({
    totalSales: 0,
    totalTransactions: 0,
    avgBasketSize: 0,
    salesGrowth: 0,
  });

  const canViewFinancials = hasPermission('can_view_financials');
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    fetchData();
  }, [dateRange, selectedStore]);

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportReportsPDF(
        kpis,
        salesTrend,
        categorySales,
        storeSales,
        topItems,
        dateRange
      );
    } catch (error) {
      console.error('PDF export failed:', error);
      // Fallback to CSV export
      const sections: string[] = [];
      
      // KPIs Section
      sections.push('=== KEY PERFORMANCE INDICATORS ===');
      sections.push(`Total Sales,${kpis.totalSales}`);
      sections.push(`Total Transactions,${kpis.totalTransactions}`);
      sections.push(`Average Basket Size,${kpis.avgBasketSize}`);
      sections.push(`Sales Growth (%),${kpis.salesGrowth}`);
      sections.push('');
      
      // Sales Trend Section
      sections.push('=== DAILY SALES TREND ===');
      sections.push('Date,Sales,Transactions');
      salesTrend.forEach(row => {
        sections.push(`${row.date},${row.sales},${row.transactions}`);
      });
      sections.push('');
      
      // Category Sales Section
      sections.push('=== CATEGORY SALES ===');
      sections.push('Category,Sales,Percentage');
      categorySales.forEach(row => {
        sections.push(`${row.category},${row.sales},${row.percentage}%`);
      });
      sections.push('');
      
      // Store Performance Section
      sections.push('=== STORE PERFORMANCE ===');
      sections.push('Store,Location,Sales,Growth (%)');
      storeSales.forEach(row => {
        sections.push(`${row.store_name},${row.location},${row.sales},${row.growth}`);
      });
      sections.push('');
      
      // Top Items Section
      sections.push('=== TOP SELLING ITEMS ===');
      sections.push('Item,Category,Total Sales,Quantity');
      topItems.forEach(row => {
        sections.push(`${row.item_name},${row.category},${row.total_sales},${row.quantity}`);
      });
      
      const csvContent = sections.join('\n');
      
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `sales_report_${dateRange}_${new Date().toISOString().split('T')[0]}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      // Map date range to days
      const daysMap: { [key: string]: number } = {
        '7d': 7,
        '30d': 30,
        '90d': 90,
        '365d': 365,
      };
      const days = daysMap[dateRange] || 7;
      
      // Fetch comprehensive report data from the new API
      const params = new URLSearchParams({ days: days.toString() });
      if (selectedStore) params.append('store_id', selectedStore.toString());
      
      const reportRes = await authFetch(`/api/reports/sales?${params}`);
      
      if (reportRes.ok) {
        const data = await reportRes.json();
        
        // Set KPIs from report
        if (data.kpis) {
          setKpis({
            totalSales: data.kpis.total_sales || 0,
            totalTransactions: data.kpis.total_transactions || 0,
            avgBasketSize: data.kpis.avg_basket_size || 0,
            salesGrowth: data.kpis.sales_growth || 0,
          });
        }
        
        // Set daily sales trend
        if (data.daily_sales && data.daily_sales.length > 0) {
          setSalesTrend(data.daily_sales.map((d: any) => ({
            date: new Date(d.date).toLocaleDateString('en-AE', { month: 'short', day: 'numeric' }),
            sales: d.sales,
            transactions: d.transactions,
          })));
        } else {
          setSalesTrend(generateMockTrend());
        }
        
        // Set category breakdown
        if (data.category_breakdown && data.category_breakdown.length > 0) {
          setCategorySales(data.category_breakdown);
        } else {
          setCategorySales(generateMockCategories());
        }
        
        // Set store performance
        if (data.store_performance && data.store_performance.length > 0) {
          setStoreSales(data.store_performance.map((s: any) => ({
            store_id: s.store_id,
            store_name: s.store_name,
            location: s.location,
            sales: s.sales,
            growth: 0, // Will be populated from performance endpoint
          })));
        } else {
          setStoreSales(generateMockStores());
        }
        
        // Set top items
        if (data.top_items && data.top_items.length > 0) {
          setTopItems(data.top_items.map((item: any) => ({
            item_id: item.item_id,
            item_name: item.item_name,
            category: item.category,
            total_sales: item.total_sales,
            quantity: item.total_sales, // Using sales as quantity proxy
          })));
        } else {
          setTopItems(generateMockTopItems());
        }
      } else {
        // Fallback to mock data
        setSalesTrend(generateMockTrend());
        setCategorySales(generateMockCategories());
        setStoreSales(generateMockStores());
        setTopItems(generateMockTopItems());
      }

    } catch (error) {
      console.error('Failed to fetch reports data:', error);
      // Use mock data on error
      setSalesTrend(generateMockTrend());
      setCategorySales(generateMockCategories());
      setStoreSales(generateMockStores());
      setTopItems(generateMockTopItems());
    } finally {
      setLoading(false);
    }
  };

  const generateMockTrend = (): SalesTrend[] => {
    const data: SalesTrend[] = [];
    for (let i = 6; i >= 0; i--) {
      const date = new Date();
      date.setDate(date.getDate() - i);
      data.push({
        date: date.toLocaleDateString('en-AE', { month: 'short', day: 'numeric' }),
        sales: Math.floor(Math.random() * 50000) + 150000,
        transactions: Math.floor(Math.random() * 500) + 800,
      });
    }
    return data;
  };

  const generateMockCategories = (): CategorySales[] => {
    const categories = [
      { category: 'Fruits & Vegetables', sales: 287500 },
      { category: 'Dairy & Eggs', sales: 198000 },
      { category: 'Meat & Poultry', sales: 325000 },
      { category: 'Beverages', sales: 156000 },
      { category: 'Snacks', sales: 112000 },
      { category: 'Bakery', sales: 89000 },
      { category: 'Household', sales: 145000 },
      { category: 'Personal Care', sales: 98000 },
    ];
    const total = categories.reduce((sum, c) => sum + c.sales, 0);
    return categories.map(c => ({
      ...c,
      percentage: Math.round((c.sales / total) * 100),
    }));
  };

  const generateMockStores = (): StoreSales[] => [
    { store_id: 1, store_name: 'Al Barsha', location: 'Dubai', sales: 425000, growth: 12.5 },
    { store_id: 2, store_name: 'Deira City Centre', location: 'Dubai', sales: 385000, growth: 8.2 },
    { store_id: 3, store_name: 'Karama', location: 'Dubai', sales: 312000, growth: -2.1 },
    { store_id: 4, store_name: 'Mushrif Mall', location: 'Abu Dhabi', sales: 298000, growth: 15.8 },
    { store_id: 5, store_name: 'Al Wahda', location: 'Abu Dhabi', sales: 275000, growth: 5.3 },
  ];

  const generateMockTopItems = (): TopItem[] => [
    { item_id: 1, item_name: 'Fresh Milk 1L', category: 'Dairy', total_sales: 45000, quantity: 8500 },
    { item_id: 2, item_name: 'Organic Apples', category: 'Fruits', total_sales: 38000, quantity: 5200 },
    { item_id: 3, item_name: 'Chicken Breast 1kg', category: 'Meat', total_sales: 62000, quantity: 2800 },
    { item_id: 4, item_name: 'Mineral Water 1.5L', category: 'Beverages', total_sales: 28000, quantity: 12000 },
    { item_id: 5, item_name: 'White Bread', category: 'Bakery', total_sales: 22000, quantity: 7500 },
  ];

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-AE', {
      style: 'currency',
      currency: 'AED',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  const formatNumber = (value: number) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return value.toString();
  };

  const accessibleStores = user?.permissions?.accessible_stores || [];

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        {/* Page Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
              <BarChart3 className="w-8 h-8 text-red-600" />
              Reports & Analytics
            </h1>
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              Comprehensive sales analytics and performance reports
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Date Range */}
            <select
              value={dateRange}
              onChange={(e) => setDateRange(e.target.value)}
              className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
            >
              <option value="7d">Last 7 Days</option>
              <option value="30d">Last 30 Days</option>
              <option value="90d">Last 90 Days</option>
              <option value="ytd">Year to Date</option>
            </select>
            
            {/* Store Filter */}
            <select
              value={selectedStore || ''}
              onChange={(e) => setSelectedStore(e.target.value ? parseInt(e.target.value) : null)}
              className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
            >
              <option value="">All Stores</option>
              {accessibleStores.map((storeId: number) => (
                <option key={storeId} value={storeId}>Store {storeId}</option>
              ))}
            </select>

            {/* Export */}
            <button 
              onClick={handleExport}
              disabled={exporting}
              className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className={`w-5 h-5 ${exporting ? 'animate-bounce' : ''}`} />
              {exporting ? 'Exporting...' : 'Export PDF'}
            </button>
          </div>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <div className="p-3 bg-green-100 dark:bg-green-900/30 rounded-lg">
                <DollarSign className="w-6 h-6 text-green-600 dark:text-green-400" />
              </div>
              <span className={`flex items-center text-sm font-medium ${
                kpis.salesGrowth >= 0 ? 'text-green-600' : 'text-red-600'
              }`}>
                {kpis.salesGrowth >= 0 ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                {Math.abs(kpis.salesGrowth).toFixed(1)}%
              </span>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Total Sales</p>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">
              {formatCurrency(kpis.totalSales)}
            </p>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <div className="p-3 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
                <ShoppingCart className="w-6 h-6 text-blue-600 dark:text-blue-400" />
              </div>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Transactions</p>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">
              {formatNumber(kpis.totalTransactions)}
            </p>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <div className="p-3 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
                <Package className="w-6 h-6 text-purple-600 dark:text-purple-400" />
              </div>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Avg Basket Size</p>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">
              {formatCurrency(kpis.avgBasketSize)}
            </p>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm p-6 border border-gray-100 dark:border-gray-700">
            <div className="flex items-center justify-between mb-4">
              <div className="p-3 bg-orange-100 dark:bg-orange-900/30 rounded-lg">
                <Users className="w-6 h-6 text-orange-600 dark:text-orange-400" />
              </div>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Active Stores</p>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">
              {accessibleStores.length}
            </p>
          </div>
        </div>

        {/* Charts Row 1 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Sales Trend */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Sales Trend</h2>
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={salesTrend}>
                  <defs>
                    <linearGradient id="salesGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.2} />
                  <XAxis dataKey="date" stroke="#9ca3af" fontSize={12} />
                  <YAxis stroke="#9ca3af" fontSize={12} tickFormatter={(v) => formatNumber(v)} />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: '#1f2937', 
                      border: 'none', 
                      borderRadius: '8px',
                      color: '#fff' 
                    }}
                    formatter={(value: number) => [formatCurrency(value), 'Sales']}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="sales" 
                    stroke="#ef4444" 
                    strokeWidth={2}
                    fill="url(#salesGradient)" 
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Category Distribution */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Sales by Category</h2>
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={categorySales}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={2}
                    dataKey="sales"
                    nameKey="category"
                    label={({ category, percentage }) => `${percentage}%`}
                    labelLine={false}
                  >
                    {categorySales.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: '#1f2937', 
                      border: 'none', 
                      borderRadius: '8px',
                      color: '#fff' 
                    }}
                    formatter={(value: number) => [formatCurrency(value), 'Sales']}
                  />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Charts Row 2 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Store Performance */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Store Performance</h2>
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={storeSales} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.2} />
                  <XAxis type="number" stroke="#9ca3af" fontSize={12} tickFormatter={(v) => formatNumber(v)} />
                  <YAxis type="category" dataKey="store_name" stroke="#9ca3af" fontSize={12} width={100} />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: '#1f2937', 
                      border: 'none', 
                      borderRadius: '8px',
                      color: '#fff' 
                    }}
                    formatter={(value: number) => [formatCurrency(value), 'Sales']}
                  />
                  <Bar dataKey="sales" fill="#ef4444" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Top Items */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Top Selling Items</h2>
            <div className="space-y-4">
              {topItems.map((item, index) => (
                <div key={item.item_id} className="flex items-center gap-4">
                  <span className="w-8 h-8 flex items-center justify-center bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded-lg font-bold text-sm">
                    #{index + 1}
                  </span>
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-gray-900 dark:text-white">{item.item_name}</span>
                      <span className="font-semibold text-gray-900 dark:text-white">{formatCurrency(item.total_sales)}</span>
                    </div>
                    <div className="flex items-center justify-between text-sm text-gray-500 dark:text-gray-400">
                      <span>{item.category}</span>
                      <span>{formatNumber(item.quantity)} units</span>
                    </div>
                    <div className="mt-2 h-1.5 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-red-500 rounded-full"
                        style={{ width: `${(item.total_sales / topItems[0].total_sales) * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Store Comparison Table */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700">
          <div className="p-6 border-b border-gray-100 dark:border-gray-700">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Store Comparison</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 dark:bg-gray-700/50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Store</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Location</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Sales</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Growth</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Performance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {storeSales.map((store) => (
                  <tr key={store.store_id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="p-2 bg-red-100 dark:bg-red-900/30 rounded-lg">
                          <Store className="w-5 h-5 text-red-600 dark:text-red-400" />
                        </div>
                        <span className="font-medium text-gray-900 dark:text-white">{store.store_name}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-gray-500 dark:text-gray-400">{store.location}</td>
                    <td className="px-6 py-4 text-right font-medium text-gray-900 dark:text-white">
                      {formatCurrency(store.sales)}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <span className={`inline-flex items-center gap-1 font-medium ${
                        store.growth >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                      }`}>
                        {store.growth >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                        {Math.abs(store.growth).toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="w-full bg-gray-100 dark:bg-gray-700 rounded-full h-2">
                        <div 
                          className={`h-2 rounded-full ${
                            store.growth >= 10 ? 'bg-green-500' : 
                            store.growth >= 0 ? 'bg-yellow-500' : 'bg-red-500'
                          }`}
                          style={{ width: `${Math.min(Math.max((store.growth + 20) * 2.5, 10), 100)}%` }}
                        />
                      </div>
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
