'use client';

import { useState, useEffect, useMemo } from 'react';
import { Package, Bell, ShoppingCart } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useEventStream } from '@/hooks/useEventStream';
import { PageHeader, Tabs, LiveIndicator, Badge, ConnectionBanner } from '@/components/ui';
import {
  InventoryFilters,
  InventorySummaryCards,
  InventoryTable,
  AlertsPanel,
  ProcurementPanel,
  ProcurementModal,
  InventoryItem,
  InventorySummary,
  CategoryData,
  ProcurementItem,
  InventoryAlert,
  generateMockInventory,
  generateMockSummary,
  generateMockCategories,
  generateAlerts,
  generateProcurementList,
} from '@/components/inventory';

export default function InventoryPage() {
  const { authFetch, hasPermission } = useAuth();
  const { t } = useLanguage();
  const [summary, setSummary] = useState<InventorySummary | null>(null);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [categories, setCategories] = useState<CategoryData[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStore, setSelectedStore] = useState<number | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [selectedStatus, setSelectedStatus] = useState<string>('');

  const [activeTab, setActiveTab] = useState<'inventory' | 'alerts' | 'procurement'>('inventory');
  const [alerts, setAlerts] = useState<InventoryAlert[]>([]);
  const [procurementList, setProcurementList] = useState<ProcurementItem[]>([]);
  const [showProcurementModal, setShowProcurementModal] = useState(false);
  const [selectedItem, setSelectedItem] = useState<InventoryItem | null>(null);
  const [procurementQuantity, setProcurementQuantity] = useState<number>(0);

  const canManageInventory = hasPermission('can_manage_inventory');
  const canApproveProcurement = hasPermission('can_approve_procurement') || hasPermission('can_manage_inventory');

  const eventHandlers = useMemo(() => ({
    alert: (alert: any) => {
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

        if (alert.type === 'out_of_stock') {
          setSummary(prev => prev ? { ...prev, out_of_stock_count: (prev.out_of_stock_count || 0) + 1 } : prev);
        } else if (alert.type === 'low_stock') {
          setSummary(prev => prev ? { ...prev, low_stock_count: (prev.low_stock_count || 0) + 1 } : prev);
        } else if (alert.type === 'overstocked') {
          setSummary(prev => prev ? { ...prev, overstocked_count: (prev.overstocked_count || 0) + 1 } : prev);
        }
      }
    }
  }), []);

  const { isConnected: isLiveConnected, error: liveError } = useEventStream('/stream/alerts', { eventHandlers });

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
        setSummary(summaryData && summaryData.total_items > 0 ? summaryData : generateMockSummary());
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
        setCategories(data.categories && data.categories.length > 0 ? data.categories : generateMockCategories());
      } else {
        setCategories(generateMockCategories());
      }

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

  const createOrderFromAlert = (alert: InventoryAlert) => {
    const item = items.find(i => i.item_name === alert.item_name && i.store_name === alert.store_name);
    if (item) addToProcurement(item);
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

  const unacknowledgedAlerts = alerts.filter(a => !a.acknowledged).length;
  const pendingProcurement = procurementList.filter(p => p.status === 'pending').length;

  const stockSummary = useMemo(() => ({
    inStock: items.filter(i => i.status === 'in_stock').length,
    lowStock: items.filter(i => i.status === 'low_stock').length,
    outOfStock: items.filter(i => i.status === 'out_of_stock').length,
    overStock: items.filter(i => i.status === 'overstocked').length,
  }), [items]);

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title={t('inventory.title')}
          description={t('inventory.description')}
          icon={<Package className="w-5 h-5" />}
          actions={isLiveConnected ? <LiveIndicator tone="teal" /> : undefined}
        />

        <ConnectionBanner connected={isLiveConnected} show={!!liveError} />

        <Tabs
          className="mb-6"
          value={activeTab}
          onChange={(id) => setActiveTab(id as typeof activeTab)}
          items={[
            { id: 'inventory', label: t('inventory.tab.inventory'), icon: <Package className="w-4 h-4" /> },
            {
              id: 'alerts', label: t('inventory.tab.alerts'), icon: <Bell className="w-4 h-4" />,
              badge: unacknowledgedAlerts > 0 && <Badge variant="danger" size="sm">{unacknowledgedAlerts}</Badge>,
            },
            {
              id: 'procurement', label: t('inventory.tab.procurement'), icon: <ShoppingCart className="w-4 h-4" />,
              badge: pendingProcurement > 0 && <Badge variant="warning" size="sm">{pendingProcurement}</Badge>,
            },
          ]}
        />

        <InventorySummaryCards summary={summary} stockSummary={stockSummary} pendingProcurement={pendingProcurement} />

        {activeTab === 'inventory' && (
          <>
            <InventoryFilters
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              selectedStore={selectedStore}
              onStoreChange={setSelectedStore}
              selectedCategory={selectedCategory}
              onCategoryChange={setSelectedCategory}
              categories={categories}
              selectedStatus={selectedStatus}
              onStatusChange={setSelectedStatus}
              onRefresh={fetchData}
              loading={loading}
            />
            <InventoryTable
              items={filteredItems}
              loading={loading}
              canManageInventory={canManageInventory}
              onAddToProcurement={addToProcurement}
            />
          </>
        )}

        {activeTab === 'alerts' && (
          <AlertsPanel
            alerts={alerts}
            unacknowledgedAlerts={unacknowledgedAlerts}
            canManageInventory={canManageInventory}
            onAcknowledge={acknowledgeAlert}
            onMarkAllRead={() => setAlerts(prev => prev.map(a => ({ ...a, acknowledged: true })))}
            onCreateOrder={createOrderFromAlert}
          />
        )}

        {activeTab === 'procurement' && (
          <ProcurementPanel
            procurementList={procurementList}
            pendingProcurement={pendingProcurement}
            canApproveProcurement={canApproveProcurement}
            onApprove={(id) => handleProcurementAction(id, 'approved')}
            onReject={(id) => handleProcurementAction(id, 'rejected')}
          />
        )}

        <ProcurementModal
          open={showProcurementModal}
          item={selectedItem}
          quantity={procurementQuantity}
          onQuantityChange={setProcurementQuantity}
          onCancel={() => setShowProcurementModal(false)}
          onConfirm={confirmAddToProcurement}
        />
      </div>
    </main>
  );
}
