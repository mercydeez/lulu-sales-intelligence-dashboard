'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
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
  PromotionTab,
} from '@/components/promotions';
import { usePromotionOverview, usePromotionList, promotionsKeys } from '@/lib/queries/promotions';

export default function PromotionsPage() {
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const canManagePromotions = hasPermission('can_manage_promotions');

  const [selectedTab, setSelectedTab] = useState<PromotionTab>('active');
  const [search, setSearch] = useState('');
  const [showModal, setShowModal] = useState(false);

  const { summary, activePromotions, categories, loading } = usePromotionOverview();
  const listQuery = usePromotionList(selectedTab);
  const listPromotions: Promotion[] = listQuery.data ?? [];
  const listLoading = listQuery.isLoading;

  // Refresh / post-create: invalidate the whole promotions domain so overview +
  // list both refetch (replaces the old refreshKey remount).
  const refreshAll = () => queryClient.invalidateQueries({ queryKey: promotionsKeys.all });
  const handleCreated = refreshAll;

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title="Promotions & Pricing"
          description="Manage promotional campaigns and track discount performance"
          icon={<Tag className="w-5 h-5" />}
          actions={
            <>
              <Button variant="secondary" size="md" onClick={refreshAll} aria-label="Refresh">
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
