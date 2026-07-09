'use client';

import { useState, useEffect, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { Package, Bell, ShoppingCart } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useEventStream } from '@/hooks/useEventStream';
import { PageHeader, Tabs, LiveIndicator, Badge, ConnectionBanner, ErrorState, Card, Reveal } from '@/components/ui';
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
  generateAlerts,
  generateProcurementList,
} from '@/components/inventory';

export default function InventoryPage() {
  const { authFetch, hasPermission } = useAuth();
  const { t } = useLanguage();
  const searchParams = useSearchParams();
  const [summary, setSummary] = useState<InventorySummary | null>(null);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [categories, setCategories] = useState<CategoryData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStore, setSelectedStore] = useState<number | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [selectedStatus, setSelectedStatus] = useState<string>(searchParams.get('status') || '');

  const initialTab = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<'inventory' | 'alerts' | 'procurement'>(
    initialTab === 'alerts' || initialTab === 'procurement' ? initialTab : 'inventory'
  );
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
    const linkedStatus = searchParams.get('status') || '';
    const linkedTab = searchParams.get('tab');
    setSelectedStatus(linkedStatus);
    if (linkedTab === 'alerts' || linkedTab === 'procurement') {
      setActiveTab(linkedTab);
    } else if (linkedStatus) {
      setActiveTab('inventory');
    }
  }, [searchParams]);

  useEffect(() => {
    fetchData();
  }, [selectedStore, selectedCategory, selectedStatus]);

  const fetchData = async () => {
    setLoading(true);
    setError(false);
    try {
      const params = new URLSearchParams();
      if (selectedStore) params.append('store_id', selectedStore.toString());
      if (selectedCategory) params.append('category', selectedCategory);
      if (selectedStatus) params.append('status', selectedStatus);

      const [summaryRes, itemsRes, categoriesRes] = await Promise.all([
        authFetch(`/api/inventory/summary?${params}`),
        // limit=500 = full derived inventory (10 stores x 50 items), so the
        // table always holds the same row set the summary KPIs count.
        authFetch(`/api/inventory/items?${params}&limit=500`),
        authFetch(`/api/inventory/categories?${params}`),
      ]);

      // The table and the KPI cards must come from the same fetch cycle: a
      // failed items query with a live summary would render "Total items: N"
      // next to an empty table, so treat either failure as a page error.
      if (!itemsRes.ok || !summaryRes.ok) {
        throw new Error('Inventory API request failed');
      }

      const summaryData = await summaryRes.json();
      setSummary(summaryData && summaryData.total_items > 0 ? summaryData : null);

      const itemsData = await itemsRes.json();
      const inventoryItems: InventoryItem[] =
        itemsData.items && itemsData.items.length > 0 ? itemsData.items : [];
      setItems(inventoryItems);

      if (categoriesRes.ok) {
        const data = await categoriesRes.json();
        setCategories(data.categories && data.categories.length > 0 ? data.categories : []);
      } else {
        setCategories([]);
      }

      // Alerts and procurement are derived from the real items list (empty when
      // there are no items) — never from fabricated data.
      setAlerts(generateAlerts(inventoryItems));
      setProcurementList(generateProcurementList(inventoryItems));
    } catch (err) {
      console.error('Failed to fetch inventory data:', err);
      setError(true);
      setSummary(null);
      setItems([]);
      setCategories([]);
      setAlerts([]);
      setProcurementList([]);
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

        {error && !loading ? (
          <Card padding="lg">
            <ErrorState
              title="Couldn't load inventory"
              description="The inventory service didn't respond. Check your connection and try again."
              onRetry={fetchData}
            />
          </Card>
        ) : (
        <>
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
          <Reveal key="tab-inventory">
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
              emptyTitle={selectedStatus ? 'No ' + selectedStatus.replace(/_/g, ' ') + ' items found' : 'No items found'}
              emptyDescription={selectedStatus
                ? 'The current inventory list has no items matching this linked status for your store scope. Use Refresh to re-check live inventory data.'
                : 'Try adjusting your filters or search query.'}
            />
          </Reveal>
        )}

        {activeTab === 'alerts' && (
          <Reveal key="tab-alerts">
            <AlertsPanel
              alerts={alerts}
              unacknowledgedAlerts={unacknowledgedAlerts}
              canManageInventory={canManageInventory}
              onAcknowledge={acknowledgeAlert}
              onMarkAllRead={() => setAlerts(prev => prev.map(a => ({ ...a, acknowledged: true })))}
              onCreateOrder={createOrderFromAlert}
            />
          </Reveal>
        )}

        {activeTab === 'procurement' && (
          <Reveal key="tab-procurement">
            <ProcurementPanel
              procurementList={procurementList}
              pendingProcurement={pendingProcurement}
              canApproveProcurement={canApproveProcurement}
              onApprove={(id) => handleProcurementAction(id, 'approved')}
              onReject={(id) => handleProcurementAction(id, 'rejected')}
            />
          </Reveal>
        )}
        </>
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
