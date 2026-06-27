'use client';

import { useMemo } from 'react';
import { Search, Percent, Calendar, Gift } from 'lucide-react';
import { Card, Tabs, Input, Badge, EmptyState, SkeletonText } from '@/components/ui';
import { Promotion, PromotionTab } from './types';
import { discountDisplay, formatCurrency, formatNumber, formatDate, statusVariant } from './format';

interface PromotionsListProps {
  promotions: Promotion[];
  loading: boolean;
  activeTab: PromotionTab;
  onTabChange: (tab: PromotionTab) => void;
  search: string;
  onSearchChange: (value: string) => void;
}

const TABS: { id: PromotionTab; label: string }[] = [
  { id: 'active', label: 'Active' },
  { id: 'scheduled', label: 'Scheduled' },
  { id: 'ended', label: 'Ended' },
  { id: 'all', label: 'All' },
];

export function PromotionsList({
  promotions,
  loading,
  activeTab,
  onTabChange,
  search,
  onSearchChange,
}: PromotionsListProps) {
  const filtered = useMemo(
    () =>
      promotions.filter(
        (p) =>
          p.name.toLowerCase().includes(search.toLowerCase()) ||
          (p.category ?? '').toLowerCase().includes(search.toLowerCase())
      ),
    [promotions, search]
  );

  return (
    <Card variant="glass" padding="none">
      <div className="flex flex-wrap items-center justify-between gap-3 p-4 border-b border-line">
        <Tabs items={TABS} value={activeTab} onChange={(id) => onTabChange(id as PromotionTab)} />
        <div className="w-full sm:w-64">
          <Input
            icon={<Search className="w-4 h-4" />}
            placeholder="Search promotions..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="!py-2.5"
          />
        </div>
      </div>

      {loading ? (
        <div className="p-5">
          <SkeletonText lines={6} />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No promotions found"
          description={search ? 'Try a different search term.' : 'Nothing in this category yet.'}
        />
      ) : (
        <div className="divide-y divide-line">
          {filtered.map((promo) => (
            <div key={`${promo.source ?? 'gen'}-${promo.id}`} className="p-4 hover:bg-surface-2/60 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-1 flex-wrap">
                    <h3 className="font-medium text-ink">{promo.name}</h3>
                    <Badge variant={statusVariant(promo.status)} size="sm">{promo.status}</Badge>
                    {promo.promotion_code && (
                      <span className="text-xs font-mono text-ink-muted">{promo.promotion_code}</span>
                    )}
                  </div>
                  <p className="text-sm text-ink-muted mb-2 line-clamp-1">{promo.description}</p>
                  <div className="flex items-center gap-4 text-sm text-ink-muted flex-wrap">
                    <span className="flex items-center gap-1">
                      <Percent className="w-4 h-4" />
                      {discountDisplay(promo)}
                    </span>
                    <span className="flex items-center gap-1">
                      <Calendar className="w-4 h-4" />
                      {formatDate(promo.start_date)} – {formatDate(promo.end_date)}
                    </span>
                    <span className="flex items-center gap-1">
                      <Gift className="w-4 h-4" />
                      {formatNumber(promo.redemption_count)} redeemed
                    </span>
                  </div>
                </div>
                <div className="text-end shrink-0">
                  <p className="text-lg font-bold text-teal-700">{formatCurrency(promo.total_discount_given)}</p>
                  <p className="text-xs text-ink-muted">total discounts</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
