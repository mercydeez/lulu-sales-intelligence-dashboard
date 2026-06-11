'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { 
  Package, AlertTriangle, TrendingDown, TrendingUp, 
  Search, Filter, RefreshCw, ArrowRightLeft, 
  ChevronDown, ChevronUp, Building2, Box, Bell,
  ShoppingCart, Check, X, Clock, Truck, AlertCircle,
  CheckCircle, FileText, Download
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useEventStream } from '@/hooks/useEventStream';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface InventoryItem {
  id: number;
  item_id: number;
  item_name: string;
  category: string;
  store_id: number;
  store_name: string;
  quantity: number;
  reorder_level: number;
  max_stock_level: number;
  unit_cost: number;
  last_restocked: string | null;
  status: 'in_stock' | 'low_stock' | 'out_of_stock' | 'overstocked';
}

interface InventorySummary {
  total_items: number;
  total_value: number;
  low_stock_count: number;
  out_of_stock_count: number;
  overstocked_count: number;
  pending_transfers: number;
  currency: string;
}

interface CategoryData {
  category: string;
  item_count: number;
  total_quantity: number;
  total_value: number;
  low_stock_count: number;
}

interface ProcurementItem {
  id: number;
  item: InventoryItem;
  suggestedQuantity: number;
  status: 'pending' | 'approved' | 'rejected' | 'ordered';
  priority: 'critical' | 'high' | 'medium' | 'low';
  createdAt: string;
  notes?: string;
}

interface InventoryAlert {
  id: number;
  item_name: string;
  store_name: string;
  type: 'out_of_stock' | 'low_stock' | 'overstocked' | 'reorder';
  message: string;
  severity: 'critical' | 'warning' | 'info';
  timestamp: string;
  acknowledged: boolean;
}

const statusColors = {
  in_stock: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
  low_stock: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
  out_of_stock: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  overstocked: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
};

const statusLabels = {
  in_stock: 'In Stock',
  low_stock: 'Low Stock',
  out_of_stock: 'Out of Stock',
  overstocked: 'Overstocked',
};

const priorityColors = {
  critical: 'bg-red-500 text-white',
  high: 'bg-orange-500 text-white',
  medium: 'bg-yellow-500 text-black',
  low: 'bg-blue-500 text-white',
};

export default function InventoryPage() {
  const { user, authFetch, hasPermission } = useAuth();
  const [summary, setSummary] = useState<InventorySummary | null>(null);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [categories, setCategories] = useState<CategoryData[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStore, setSelectedStore] = useState<number | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [selectedStatus, setSelectedStatus] = useState<string>('');
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  
  // New states for procurement and alerts
  const [activeTab, setActiveTab] = useState<'inventory' | 'alerts' | 'procurement'>('inventory');
  const [alerts, setAlerts] = useState<InventoryAlert[]>([]);
  const [procurementList, setProcurementList] = useState<ProcurementItem[]>([]);
  const [showProcurementModal, setShowProcurementModal] = useState(false);
  const [selectedItem, setSelectedItem] = useState<InventoryItem | null>(null);
  const [procurementQuantity, setProcurementQuantity] = useState<number>(0);

  const canManageInventory = hasPermission('can_manage_inventory');
  const canApproveProcurement = hasPermission('can_approve_procurement') || hasPermission('can_manage_inventory');

  // SSE Connection for real-time inventory alerts using useEventStream hook
  const eventHandlers = useMemo(() => ({
    alert: (alert: any) => {
      // Only process inventory-related alerts
      if (alert.category === 'inventory' || ['out_of_stock', 'low_stock', 'overstocked', 'reorder'].includes(alert.type)) {
        const newAlert: InventoryAlert = {
          id: alert.id,
          item_name: alert.item_name || alert.title,
          store_name: alert.store_name || 'Unknown Store',
          type: alert.type,
          message: alert.message,
          severity: alert.severity,
          timestamp: alert.timestamp || new Date().toISOString(),
          acknowledged: false,
        };
        
        setAlerts(prev => {
          const exists = prev.some(a => a.id === newAlert.id);
          if (exists) return prev;
          return [newAlert, ...prev].slice(0, 50);
        });

        // Update stock summary based on alert type
        if (alert.type === 'out_of_stock') {
          setSummary(prev => prev ? {...prev, out_of_stock_count: (prev.out_of_stock_count || 0) + 1} : prev);
        } else if (alert.type === 'low_stock') {
          setSummary(prev => prev ? {...prev, low_stock_count: (prev.low_stock_count || 0) + 1} : prev);
        } else if (alert.type === 'overstocked') {
          setSummary(prev => prev ? {...prev, overstocked_count: (prev.overstocked_count || 0) + 1} : prev);
        }
      }
    }
  }), []);

  const { isConnected: isLiveConnected } = useEventStream('/stream/alerts', { eventHandlers });

  // Generate mock data for demonstration when API returns empty
  const generateMockInventory = (): InventoryItem[] => {
    const categories = ['Dairy', 'Beverages', 'Bakery', 'Fruits', 'Vegetables', 'Meat', 'Frozen Foods', 'Household'];
    const stores = [
      { id: 1, name: 'Al Barsha' },
      { id: 2, name: 'Deira City Centre' },
      { id: 3, name: 'Karama' },
      { id: 4, name: 'Mushrif Mall' },
      { id: 5, name: 'Al Wahda' },
    ];
    const items: InventoryItem[] = [];
    let id = 1;
    
    const productNames: { [key: string]: string[] } = {
      'Dairy': ['Fresh Milk 1L', 'Greek Yogurt', 'Cheddar Cheese', 'Butter 500g', 'Cream Cheese'],
      'Beverages': ['Mineral Water 1.5L', 'Orange Juice', 'Cola 330ml', 'Green Tea', 'Coffee Beans'],
      'Bakery': ['White Bread', 'Croissants', 'Whole Wheat Bread', 'Bagels', 'Muffins'],
      'Fruits': ['Apples', 'Bananas', 'Oranges', 'Grapes', 'Mangoes'],
      'Vegetables': ['Tomatoes', 'Onions', 'Potatoes', 'Carrots', 'Lettuce'],
      'Meat': ['Chicken Breast', 'Ground Beef', 'Lamb Chops', 'Beef Steak', 'Chicken Wings'],
      'Frozen Foods': ['Frozen Pizza', 'Ice Cream', 'Frozen Vegetables', 'Fish Fingers', 'Frozen Berries'],
      'Household': ['Dish Soap', 'Laundry Detergent', 'Paper Towels', 'Garbage Bags', 'Cleaning Spray'],
    };

    categories.forEach((category, catIdx) => {
      const products = productNames[category] || [];
      products.forEach((productName, prodIdx) => {
        stores.forEach((store) => {
          const quantity = Math.floor(Math.random() * 500);
          const reorder = 50 + Math.floor(Math.random() * 30);
          const maxStock = 400 + Math.floor(Math.random() * 200);
          
          let status: 'in_stock' | 'low_stock' | 'out_of_stock' | 'overstocked' = 'in_stock';
          if (quantity <= 0) status = 'out_of_stock';
          else if (quantity <= reorder) status = 'low_stock';
          else if (quantity > maxStock) status = 'overstocked';
          
          items.push({
            id: id++,
            item_id: catIdx * 100 + prodIdx + 1,
            item_name: productName,
            category,
            store_id: store.id,
            store_name: store.name,
            quantity,
            reorder_level: reorder,
            max_stock_level: maxStock,
            unit_cost: 10 + Math.random() * 50,
            last_restocked: new Date(Date.now() - Math.random() * 7 * 24 * 60 * 60 * 1000).toISOString(),
            status,
          });
        });
      });
    });
    return items;
  };

  const generateMockSummary = (): InventorySummary => ({
    total_items: 1250,
    total_value: 2847500,
    low_stock_count: 45,
    out_of_stock_count: 12,
    overstocked_count: 8,
    pending_transfers: 5,
    currency: 'AED',
  });

  const generateMockCategories = (): CategoryData[] => [
    { category: 'Dairy', item_count: 156, total_quantity: 12500, total_value: 187500, low_stock_count: 8 },
    { category: 'Beverages', item_count: 142, total_quantity: 15800, total_value: 156000, low_stock_count: 5 },
    { category: 'Bakery', item_count: 98, total_quantity: 8200, total_value: 82000, low_stock_count: 12 },
    { category: 'Fruits', item_count: 125, total_quantity: 9500, total_value: 142500, low_stock_count: 6 },
    { category: 'Vegetables', item_count: 180, total_quantity: 14200, total_value: 142000, low_stock_count: 4 },
    { category: 'Meat', item_count: 85, total_quantity: 4200, total_value: 378000, low_stock_count: 3 },
    { category: 'Frozen Foods', item_count: 120, total_quantity: 8800, total_value: 220000, low_stock_count: 2 },
    { category: 'Household', item_count: 95, total_quantity: 11200, total_value: 336000, low_stock_count: 5 },
  ];

  // Generate alerts based on inventory items
  const generateAlerts = (inventoryItems: InventoryItem[]): InventoryAlert[] => {
    const alerts: InventoryAlert[] = [];
    let alertId = 1;

    inventoryItems.forEach(item => {
      if (item.status === 'out_of_stock') {
        alerts.push({
          id: alertId++,
          item_name: item.item_name,
          store_name: item.store_name,
          type: 'out_of_stock',
          message: `${item.item_name} is out of stock at ${item.store_name}. Immediate reorder required!`,
          severity: 'critical',
          timestamp: new Date(Date.now() - Math.random() * 3600000).toISOString(),
          acknowledged: false,
        });
      } else if (item.status === 'low_stock') {
        alerts.push({
          id: alertId++,
          item_name: item.item_name,
          store_name: item.store_name,
          type: 'low_stock',
          message: `${item.item_name} is running low at ${item.store_name}. Current stock: ${item.quantity} (Reorder level: ${item.reorder_level})`,
          severity: 'warning',
          timestamp: new Date(Date.now() - Math.random() * 7200000).toISOString(),
          acknowledged: false,
        });
      } else if (item.status === 'overstocked') {
        alerts.push({
          id: alertId++,
          item_name: item.item_name,
          store_name: item.store_name,
          type: 'overstocked',
          message: `${item.item_name} is overstocked at ${item.store_name}. Current: ${item.quantity} (Max: ${item.max_stock_level})`,
          severity: 'info',
          timestamp: new Date(Date.now() - Math.random() * 14400000).toISOString(),
          acknowledged: false,
        });
      }
    });

    return alerts.sort((a, b) => {
      const severityOrder = { critical: 0, warning: 1, info: 2 };
      return severityOrder[a.severity] - severityOrder[b.severity];
    }).slice(0, 50);
  };

  // Generate procurement suggestions
  const generateProcurementList = (inventoryItems: InventoryItem[]): ProcurementItem[] => {
    const procurement: ProcurementItem[] = [];
    let procId = 1;

    inventoryItems
      .filter(item => item.status === 'out_of_stock' || item.status === 'low_stock')
      .forEach(item => {
        const suggestedQty = item.status === 'out_of_stock' 
          ? item.max_stock_level 
          : item.reorder_level * 2 - item.quantity;
        
        procurement.push({
          id: procId++,
          item,
          suggestedQuantity: Math.max(suggestedQty, item.reorder_level),
          status: 'pending',
          priority: item.status === 'out_of_stock' ? 'critical' : 
                   item.quantity < item.reorder_level / 2 ? 'high' : 'medium',
          createdAt: new Date().toISOString(),
        });
      });

    return procurement.sort((a, b) => {
      const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
      return priorityOrder[a.priority] - priorityOrder[b.priority];
    });
  };

  useEffect(() => {
    fetchData();
  }, [selectedStore, selectedCategory, selectedStatus]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (selectedStore) params.append('store_id', selectedStore.toString());
      if (selectedCategory) params.append('category', selectedCategory);
      if (selectedStatus) params.append('status', selectedStatus);

      const [summaryRes, itemsRes, categoriesRes] = await Promise.all([
        authFetch(`/api/inventory/summary?${params}`),
        authFetch(`/api/inventory/items?${params}&limit=200`),
        authFetch(`/api/inventory/categories?${params}`),
      ]);

      let inventoryItems: InventoryItem[] = [];

      if (summaryRes.ok) {
        const summaryData = await summaryRes.json();
        if (summaryData && summaryData.total_items > 0) {
          setSummary(summaryData);
        } else {
          setSummary(generateMockSummary());
        }
      } else {
        setSummary(generateMockSummary());
      }
      
      if (itemsRes.ok) {
        const data = await itemsRes.json();
        if (data.items && data.items.length > 0) {
          inventoryItems = data.items;
          setItems(data.items);
        } else {
          inventoryItems = generateMockInventory();
          setItems(inventoryItems.slice(0, 100));
        }
      } else {
        inventoryItems = generateMockInventory();
        setItems(inventoryItems.slice(0, 100));
      }
      
      if (categoriesRes.ok) {
        const data = await categoriesRes.json();
        if (data.categories && data.categories.length > 0) {
          setCategories(data.categories);
        } else {
          setCategories(generateMockCategories());
        }
      } else {
        setCategories(generateMockCategories());
      }

      // Generate alerts and procurement list from inventory data
      setAlerts(generateAlerts(inventoryItems));
      setProcurementList(generateProcurementList(inventoryItems));

    } catch (error) {
      console.error('Failed to fetch inventory data:', error);
      const mockItems = generateMockInventory();
      setSummary(generateMockSummary());
      setItems(mockItems.slice(0, 100));
      setCategories(generateMockCategories());
      setAlerts(generateAlerts(mockItems));
      setProcurementList(generateProcurementList(mockItems));
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-AE', {
      style: 'currency',
      currency: 'AED',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  const formatNumber = (value: number) => {
    return new Intl.NumberFormat('en-AE').format(value);
  };

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return date.toLocaleDateString();
  };

  const filteredItems = useMemo(() => items.filter(item =>
    item.item_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.category.toLowerCase().includes(searchQuery.toLowerCase()) ||
    item.store_name.toLowerCase().includes(searchQuery.toLowerCase())
  ), [items, searchQuery]);

  const acknowledgeAlert = (alertId: number) => {
    setAlerts(prev => prev.map(alert => 
      alert.id === alertId ? { ...alert, acknowledged: true } : alert
    ));
  };

  const handleProcurementAction = (procId: number, action: 'approved' | 'rejected') => {
    setProcurementList(prev => prev.map(item =>
      item.id === procId ? { ...item, status: action } : item
    ));
  };

  const addToProcurement = (item: InventoryItem) => {
    setSelectedItem(item);
    setProcurementQuantity(Math.max(item.reorder_level * 2 - item.quantity, item.reorder_level));
    setShowProcurementModal(true);
  };

  const confirmAddToProcurement = () => {
    if (!selectedItem) return;
    
    const newProcItem: ProcurementItem = {
      id: Date.now(),
      item: selectedItem,
      suggestedQuantity: procurementQuantity,
      status: 'pending',
      priority: selectedItem.status === 'out_of_stock' ? 'critical' : 'high',
      createdAt: new Date().toISOString(),
    };
    
    setProcurementList(prev => [newProcItem, ...prev]);
    setShowProcurementModal(false);
    setSelectedItem(null);
  };

  const accessibleStores = user?.accessible_stores || user?.permissions?.accessible_stores || [];
  const unacknowledgedAlerts = alerts.filter(a => !a.acknowledged).length;
  const pendingProcurement = procurementList.filter(p => p.status === 'pending').length;

  // Stock Status Summary
  const stockSummary = useMemo(() => {
    const inStock = items.filter(i => i.status === 'in_stock').length;
    const lowStock = items.filter(i => i.status === 'low_stock').length;
    const outOfStock = items.filter(i => i.status === 'out_of_stock').length;
    const overStock = items.filter(i => i.status === 'overstocked').length;
    return { inStock, lowStock, outOfStock, overStock };
  }, [items]);

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        {/* Page Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between">
            <h1 className="text-3xl font-bold text-white flex items-center gap-3">
              <Package className="w-8 h-8 text-cyan-500" />
              Inventory & Procurement
            </h1>
            {/* Live Indicator */}
            {isLiveConnected && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-green-500/20 border border-green-500/30">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                </span>
                <span className="text-sm font-medium text-green-400">LIVE</span>
              </div>
            )}
          </div>
          <p className="mt-2 text-slate-400">
            Monitor stock levels, manage alerts, and handle procurement across all stores
          </p>
        </div>

        {/* Tab Navigation */}
        <div className="flex gap-2 mb-6 border-b border-slate-700">
          <button
            onClick={() => setActiveTab('inventory')}
            className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors border-b-2 -mb-px ${
              activeTab === 'inventory'
                ? 'text-cyan-400 border-cyan-400'
                : 'text-slate-400 border-transparent hover:text-white'
            }`}
          >
            <Package className="w-5 h-5" />
            Inventory
          </button>
          <button
            onClick={() => setActiveTab('alerts')}
            className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors border-b-2 -mb-px ${
              activeTab === 'alerts'
                ? 'text-cyan-400 border-cyan-400'
                : 'text-slate-400 border-transparent hover:text-white'
            }`}
          >
            <Bell className="w-5 h-5" />
            Alerts
            {unacknowledgedAlerts > 0 && (
              <span className="px-2 py-0.5 text-xs rounded-full bg-red-500 text-white">
                {unacknowledgedAlerts}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab('procurement')}
            className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors border-b-2 -mb-px ${
              activeTab === 'procurement'
                ? 'text-cyan-400 border-cyan-400'
                : 'text-slate-400 border-transparent hover:text-white'
            }`}
          >
            <ShoppingCart className="w-5 h-5" />
            Procurement
            {pendingProcurement > 0 && (
              <span className="px-2 py-0.5 text-xs rounded-full bg-amber-500 text-black">
                {pendingProcurement}
              </span>
            )}
          </button>
        </div>

        {/* Summary Cards - Always visible */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-8">
          <div className="glass rounded-xl p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-400">Total Items</p>
                <p className="text-2xl font-bold text-white">
                  {formatNumber(summary?.total_items || 0)}
                </p>
              </div>
              <Package className="w-10 h-10 text-slate-500" />
            </div>
          </div>

          <div className="glass rounded-xl p-4 border-green-500/30">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-green-400">In Stock</p>
                <p className="text-2xl font-bold text-green-400">
                  {stockSummary.inStock}
                </p>
              </div>
              <CheckCircle className="w-10 h-10 text-green-500" />
            </div>
          </div>

          <div className="glass rounded-xl p-4 border-yellow-500/30">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-yellow-400">Low Stock</p>
                <p className="text-2xl font-bold text-yellow-400">
                  {summary?.low_stock_count || stockSummary.lowStock}
                </p>
              </div>
              <TrendingDown className="w-10 h-10 text-yellow-500" />
            </div>
          </div>

          <div className="glass rounded-xl p-4 border-red-500/30">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-red-400">Out of Stock</p>
                <p className="text-2xl font-bold text-red-400">
                  {summary?.out_of_stock_count || stockSummary.outOfStock}
                </p>
              </div>
              <AlertTriangle className="w-10 h-10 text-red-500" />
            </div>
          </div>

          <div className="glass rounded-xl p-4 border-blue-500/30">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-blue-400">Overstocked</p>
                <p className="text-2xl font-bold text-blue-400">
                  {summary?.overstocked_count || stockSummary.overStock}
                </p>
              </div>
              <TrendingUp className="w-10 h-10 text-blue-500" />
            </div>
          </div>

          <div className="glass rounded-xl p-4 border-purple-500/30">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-purple-400">Pending Orders</p>
                <p className="text-2xl font-bold text-purple-400">
                  {pendingProcurement}
                </p>
              </div>
              <Truck className="w-10 h-10 text-purple-500" />
            </div>
          </div>
        </div>

        {/* INVENTORY TAB */}
        {activeTab === 'inventory' && (
          <>
            {/* Filters */}
            <div className="glass rounded-xl p-4 mb-6">
              <div className="flex flex-wrap items-center gap-4">
                <div className="flex-1 min-w-[200px]">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-slate-400" />
                    <input
                      type="text"
                      placeholder="Search items, categories, stores..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full pl-10 pr-4 py-2 rounded-lg border border-slate-600 bg-slate-800 text-white focus:ring-2 focus:ring-cyan-500 focus:border-transparent"
                    />
                  </div>
                </div>

                <select
                  value={selectedStore || ''}
                  onChange={(e) => setSelectedStore(e.target.value ? parseInt(e.target.value) : null)}
                  className="px-4 py-2 rounded-lg border border-slate-600 bg-slate-800 text-white"
                >
                  <option value="">All Stores</option>
                  <option value="1">Al Barsha</option>
                  <option value="2">Deira City Centre</option>
                  <option value="3">Karama</option>
                  <option value="4">Mushrif Mall</option>
                  <option value="5">Al Wahda</option>
                </select>

                <select
                  value={selectedCategory}
                  onChange={(e) => setSelectedCategory(e.target.value)}
                  className="px-4 py-2 rounded-lg border border-slate-600 bg-slate-800 text-white"
                >
                  <option value="">All Categories</option>
                  {categories.map((cat) => (
                    <option key={cat.category} value={cat.category}>{cat.category}</option>
                  ))}
                </select>

                <select
                  value={selectedStatus}
                  onChange={(e) => setSelectedStatus(e.target.value)}
                  className="px-4 py-2 rounded-lg border border-slate-600 bg-slate-800 text-white"
                >
                  <option value="">All Status</option>
                  <option value="in_stock">In Stock</option>
                  <option value="low_stock">Low Stock</option>
                  <option value="out_of_stock">Out of Stock</option>
                  <option value="overstocked">Overstocked</option>
                </select>

                <button
                  onClick={fetchData}
                  className="p-2 rounded-lg bg-cyan-600 text-white hover:bg-cyan-700 transition-colors"
                >
                  <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
                </button>
              </div>
            </div>

            {/* Inventory Table */}
            <div className="glass rounded-xl overflow-hidden">
              <div className="p-4 border-b border-slate-700 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                  <Package className="w-5 h-5 text-cyan-400" />
                  Inventory Items
                  <span className="ml-2 px-2 py-1 text-xs rounded-full bg-slate-700 text-slate-300">
                    {filteredItems.length} items
                  </span>
                </h2>
              </div>
              
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-slate-800/50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Item</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Store</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase">Qty</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase">Reorder Level</th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-slate-400 uppercase">Status</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase">Unit Cost</th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-slate-400 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700">
                    {loading ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-8 text-center text-slate-400">
                          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
                          Loading inventory...
                        </td>
                      </tr>
                    ) : filteredItems.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-8 text-center text-slate-400">
                          No items found
                        </td>
                      </tr>
                    ) : (
                      filteredItems.slice(0, 50).map((item) => (
                        <tr key={item.id} className="hover:bg-slate-700/30 transition-colors">
                          <td className="px-4 py-3">
                            <div>
                              <p className="font-medium text-white">{item.item_name}</p>
                              <p className="text-sm text-slate-400">{item.category}</p>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <Building2 className="w-4 h-4 text-slate-400" />
                              <span className="text-sm text-slate-300">{item.store_name}</span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <span className={`font-medium ${
                              item.quantity <= 0 ? 'text-red-400' : 
                              item.quantity <= item.reorder_level ? 'text-yellow-400' : 
                              'text-white'
                            }`}>
                              {formatNumber(item.quantity)}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-slate-400">
                            {formatNumber(item.reorder_level)}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <span className={`px-2 py-1 text-xs rounded-full ${statusColors[item.status]}`}>
                              {statusLabels[item.status]}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-white">
                            {formatCurrency(item.unit_cost)}
                          </td>
                          <td className="px-4 py-3 text-center">
                            {(item.status === 'out_of_stock' || item.status === 'low_stock') && canManageInventory && (
                              <button
                                onClick={() => addToProcurement(item)}
                                className="px-3 py-1 text-xs rounded-lg bg-cyan-600 text-white hover:bg-cyan-700 transition-colors"
                              >
                                Order
                              </button>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {/* ALERTS TAB */}
        {activeTab === 'alerts' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                <Bell className="w-6 h-6 text-cyan-400" />
                Inventory Alerts
                <span className="px-2 py-1 text-xs rounded-full bg-red-500/20 text-red-400">
                  {unacknowledgedAlerts} unread
                </span>
              </h2>
              <button
                onClick={() => setAlerts(prev => prev.map(a => ({ ...a, acknowledged: true })))}
                className="px-4 py-2 text-sm rounded-lg bg-slate-700 text-white hover:bg-slate-600 transition-colors"
              >
                Mark All Read
              </button>
            </div>

            {alerts.length === 0 ? (
              <div className="glass rounded-xl p-12 text-center">
                <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
                <p className="text-xl text-white mb-2">All Clear!</p>
                <p className="text-slate-400">No inventory alerts at this time</p>
              </div>
            ) : (
              <div className="space-y-3">
                {alerts.map((alert) => (
                  <div
                    key={alert.id}
                    className={`glass rounded-xl p-4 border-l-4 ${
                      alert.severity === 'critical' ? 'border-red-500' :
                      alert.severity === 'warning' ? 'border-yellow-500' : 'border-blue-500'
                    } ${alert.acknowledged ? 'opacity-60' : ''}`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-3">
                        <div className={`p-2 rounded-lg ${
                          alert.severity === 'critical' ? 'bg-red-500/20' :
                          alert.severity === 'warning' ? 'bg-yellow-500/20' : 'bg-blue-500/20'
                        }`}>
                          {alert.severity === 'critical' ? <AlertTriangle className="w-5 h-5 text-red-400" /> :
                           alert.severity === 'warning' ? <AlertCircle className="w-5 h-5 text-yellow-400" /> :
                           <TrendingUp className="w-5 h-5 text-blue-400" />}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className={`text-sm font-semibold ${
                              alert.severity === 'critical' ? 'text-red-400' :
                              alert.severity === 'warning' ? 'text-yellow-400' : 'text-blue-400'
                            }`}>
                              {alert.type.replace('_', ' ').toUpperCase()}
                            </span>
                            <span className="text-xs text-slate-500">{formatTime(alert.timestamp)}</span>
                            {!alert.acknowledged && (
                              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
                            )}
                          </div>
                          <p className="text-white font-medium mt-1">{alert.item_name}</p>
                          <p className="text-sm text-slate-400 mt-1">{alert.message}</p>
                          <div className="flex items-center gap-2 mt-2">
                            <Building2 className="w-4 h-4 text-slate-500" />
                            <span className="text-xs text-slate-500">{alert.store_name}</span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {!alert.acknowledged && (
                          <>
                            <button
                              onClick={() => acknowledgeAlert(alert.id)}
                              className="p-2 rounded-lg bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors"
                              title="Acknowledge"
                            >
                              <Check className="w-4 h-4" />
                            </button>
                            {canManageInventory && alert.type !== 'overstocked' && (
                              <button
                                onClick={() => {
                                  const item = items.find(i => i.item_name === alert.item_name && i.store_name === alert.store_name);
                                  if (item) addToProcurement(item);
                                }}
                                className="px-3 py-2 rounded-lg bg-cyan-600 text-white text-sm hover:bg-cyan-700 transition-colors"
                              >
                                Create Order
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* PROCUREMENT TAB */}
        {activeTab === 'procurement' && (
          <div className="space-y-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                <ShoppingCart className="w-6 h-6 text-cyan-400" />
                Procurement Orders
              </h2>
              <div className="flex items-center gap-2">
                <span className="px-3 py-1 text-sm rounded-full bg-amber-500/20 text-amber-400">
                  {pendingProcurement} Pending
                </span>
                <span className="px-3 py-1 text-sm rounded-full bg-green-500/20 text-green-400">
                  {procurementList.filter(p => p.status === 'approved').length} Approved
                </span>
              </div>
            </div>

            {procurementList.length === 0 ? (
              <div className="glass rounded-xl p-12 text-center">
                <Package className="w-16 h-16 text-slate-500 mx-auto mb-4" />
                <p className="text-xl text-white mb-2">No Procurement Orders</p>
                <p className="text-slate-400">All inventory levels are adequate</p>
              </div>
            ) : (
              <div className="glass rounded-xl overflow-hidden">
                <table className="w-full">
                  <thead className="bg-slate-800/50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Priority</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Item</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Store</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase">Current Stock</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase">Order Qty</th>
                      <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase">Est. Cost</th>
                      <th className="px-4 py-3 text-center text-xs font-medium text-slate-400 uppercase">Status</th>
                      {canApproveProcurement && (
                        <th className="px-4 py-3 text-center text-xs font-medium text-slate-400 uppercase">Actions</th>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700">
                    {procurementList.map((proc) => (
                      <tr key={proc.id} className="hover:bg-slate-700/30 transition-colors">
                        <td className="px-4 py-3">
                          <span className={`px-2 py-1 text-xs rounded-full ${priorityColors[proc.priority]}`}>
                            {proc.priority.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <div>
                            <p className="font-medium text-white">{proc.item.item_name}</p>
                            <p className="text-sm text-slate-400">{proc.item.category}</p>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-slate-300">{proc.item.store_name}</td>
                        <td className="px-4 py-3 text-right">
                          <span className={proc.item.quantity <= 0 ? 'text-red-400' : 'text-yellow-400'}>
                            {proc.item.quantity}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right text-white font-medium">
                          {formatNumber(proc.suggestedQuantity)}
                        </td>
                        <td className="px-4 py-3 text-right text-white">
                          {formatCurrency(proc.suggestedQuantity * proc.item.unit_cost)}
                        </td>
                        <td className="px-4 py-3 text-center">
                          <span className={`px-2 py-1 text-xs rounded-full ${
                            proc.status === 'pending' ? 'bg-amber-500/20 text-amber-400' :
                            proc.status === 'approved' ? 'bg-green-500/20 text-green-400' :
                            proc.status === 'rejected' ? 'bg-red-500/20 text-red-400' :
                            'bg-blue-500/20 text-blue-400'
                          }`}>
                            {proc.status.charAt(0).toUpperCase() + proc.status.slice(1)}
                          </span>
                        </td>
                        {canApproveProcurement && (
                          <td className="px-4 py-3 text-center">
                            {proc.status === 'pending' && (
                              <div className="flex items-center justify-center gap-2">
                                <button
                                  onClick={() => handleProcurementAction(proc.id, 'approved')}
                                  className="p-2 rounded-lg bg-green-600 text-white hover:bg-green-700 transition-colors"
                                  title="Approve Order"
                                >
                                  <Check className="w-4 h-4" />
                                </button>
                                <button
                                  onClick={() => handleProcurementAction(proc.id, 'rejected')}
                                  className="p-2 rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors"
                                  title="Reject Order"
                                >
                                  <X className="w-4 h-4" />
                                </button>
                              </div>
                            )}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Procurement Modal */}
        {showProcurementModal && selectedItem && (
          <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="glass rounded-2xl p-6 w-full max-w-md mx-4">
              <h3 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                <ShoppingCart className="w-6 h-6 text-cyan-400" />
                Create Procurement Order
              </h3>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm text-slate-400 mb-1">Item</label>
                  <p className="text-white font-medium">{selectedItem.item_name}</p>
                  <p className="text-sm text-slate-400">{selectedItem.category} • {selectedItem.store_name}</p>
                </div>
                
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-slate-400 mb-1">Current Stock</label>
                    <p className={`text-lg font-bold ${selectedItem.quantity <= 0 ? 'text-red-400' : 'text-yellow-400'}`}>
                      {selectedItem.quantity}
                    </p>
                  </div>
                  <div>
                    <label className="block text-sm text-slate-400 mb-1">Reorder Level</label>
                    <p className="text-lg font-bold text-white">{selectedItem.reorder_level}</p>
                  </div>
                </div>
                
                <div>
                  <label className="block text-sm text-slate-400 mb-1">Order Quantity</label>
                  <input
                    type="number"
                    value={procurementQuantity}
                    onChange={(e) => setProcurementQuantity(parseInt(e.target.value) || 0)}
                    min={1}
                    className="w-full px-4 py-2 rounded-lg border border-slate-600 bg-slate-800 text-white focus:ring-2 focus:ring-cyan-500"
                  />
                </div>
                
                <div>
                  <label className="block text-sm text-slate-400 mb-1">Estimated Cost</label>
                  <p className="text-xl font-bold text-cyan-400">
                    {formatCurrency(procurementQuantity * selectedItem.unit_cost)}
                  </p>
                </div>
              </div>
              
              <div className="flex gap-3 mt-6">
                <button
                  onClick={() => setShowProcurementModal(false)}
                  className="flex-1 px-4 py-2 rounded-lg bg-slate-700 text-white hover:bg-slate-600 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmAddToProcurement}
                  className="flex-1 px-4 py-2 rounded-lg bg-cyan-600 text-white hover:bg-cyan-700 transition-colors"
                >
                  Create Order
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
