'use client';

import { Tag, CalendarClock, Clock, FileText, Gift, Percent } from 'lucide-react';
import { StatCard } from '@/components/ui';
import { formatCurrency, formatNumber } from './format';
import { PromotionSummary } from './types';

interface PromotionSummaryCardsProps {
  summary: PromotionSummary | null;
  loading: boolean;
}

export function PromotionSummaryCards({ summary, loading }: PromotionSummaryCardsProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
      <StatCard
        variant="gradient"
        tone="coral"
        label="Active"
        value={loading ? '—' : summary?.active_promotions ?? 0}
        icon={<Tag className="w-5 h-5" />}
        loading={loading}
      />
      <StatCard
        tone="violet"
        label="Scheduled"
        value={loading ? '—' : summary?.scheduled_promotions ?? 0}
        icon={<CalendarClock className="w-5 h-5" />}
        loading={loading}
      />
      <StatCard
        tone="teal"
        label="Ended"
        value={loading ? '—' : summary?.ended_promotions ?? 0}
        icon={<Clock className="w-5 h-5" />}
        loading={loading}
      />
      <StatCard
        tone="amber"
        label="Drafts"
        value={loading ? '—' : summary?.draft_promotions ?? 0}
        icon={<FileText className="w-5 h-5" />}
        loading={loading}
      />
      <StatCard
        tone="violet"
        label="Redemptions"
        value={loading ? '—' : formatNumber(summary?.total_redemptions ?? 0)}
        icon={<Gift className="w-5 h-5" />}
        loading={loading}
      />
      <StatCard
        tone="coral"
        label="Total Discounts"
        value={loading ? '—' : formatCurrency(summary?.total_discounts_given ?? 0)}
        icon={<Percent className="w-5 h-5" />}
        loading={loading}
      />
    </div>
  );
}
