'use client';

import { useState, useEffect, useCallback } from 'react';
import { Tag, Plus, RefreshCw } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Button, Stagger, RevealItem } from '@/components/ui';
import {
  PromotionSummaryCards,
  ActivePromotions,
  CategoryPerformancePanel,
  PromotionsList,
  PromotionFormModal,
  Promotion,
  PromotionSummary,
  CategoryPerformance,
  PromotionTab,
} from '@/components/promotions';

export default function PromotionsPage() {
  const { authFetch, hasPermission } = useAuth();
  const canManagePromotions = hasPermission('can_manage_promotions');

  const [summary, setSummary] = useState<PromotionSummary | null>(null);
  const [activePromotions, setActivePromotions] = useState<Promotion[]>([]);
  const [categories, setCategories] = useState<CategoryPerformance[]>([]);
  const [listPromotions, setListPromotions] = useState<Promotion[]>([]);

  const [loading, setLoading] = useState(true);
  const [listLoading, setListLoading] = useState(true);
  const [selectedTab, setSelectedTab] = useState<PromotionTab>('active');
  const [search, setSearch] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryRes, activeRes, categoriesRes] = await Promise.all([
        authFetch('/api/promotions/summary'),
        authFetch('/api/promotions/active'),
        authFetch('/api/promotions/categories'),
      ]);
      if (summaryRes.ok) setSummary(await summaryRes.json());
      if (activeRes.ok) setActivePromotions((await activeRes.json()).promotions ?? []);
      if (categoriesRes.ok) setCategories((await categoriesRes.json()).categories ?? []);
    } catch (err) {
      console.error('Failed to load promotions overview:', err);
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  const loadList = useCallback(async () => {
    setListLoading(true);
    try {
      const status = selectedTab === 'all' ? '' : selectedTab;
      const res = await authFetch(`/api/promotions/list?status=${status}&limit=100`);
      if (res.ok) setListPromotions((await res.json()).promotions ?? []);
      else setListPromotions([]);
    } catch (err) {
      console.error('Failed to load promotions list:', err);
      setListPromotions([]);
    } finally {
      setListLoading(false);
    }
  }, [authFetch, selectedTab]);

  useEffect(() => {
    loadOverview();
  }, [loadOverview, refreshKey]);

  useEffect(() => {
    loadList();
  }, [loadList, refreshKey]);

  const handleCreated = () => setRefreshKey((k) => k + 1);

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title="Promotions & Pricing"
          description="Manage promotional campaigns and track discount performance"
          icon={<Tag className="w-5 h-5" />}
          actions={
            <>
              <Button variant="secondary" size="md" onClick={() => setRefreshKey((k) => k + 1)} aria-label="Refresh">
                <RefreshCw className="w-4 h-4" />
              </Button>
              {canManagePromotions && (
                <Button variant="primary" size="md" onClick={() => setShowModal(true)}>
                  <Plus className="w-4 h-4" />
                  New Promotion
                </Button>
              )}
            </>
          }
        />

        <Stagger className="space-y-6">
          <RevealItem>
            <PromotionSummaryCards summary={summary} loading={loading} />
          </RevealItem>

          <RevealItem>
            <ActivePromotions promotions={activePromotions} loading={loading} />
          </RevealItem>

          <RevealItem className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1">
              <CategoryPerformancePanel categories={categories} loading={loading} />
            </div>
            <div className="lg:col-span-2">
              <PromotionsList
                promotions={listPromotions}
                loading={listLoading}
                activeTab={selectedTab}
                onTabChange={setSelectedTab}
                search={search}
                onSearchChange={setSearch}
              />
            </div>
          </RevealItem>
        </Stagger>
      </div>

      {canManagePromotions && (
        <PromotionFormModal open={showModal} onClose={() => setShowModal(false)} onSuccess={handleCreated} />
      )}
    </main>
  );
}
