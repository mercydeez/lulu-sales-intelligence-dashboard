'use client';

import { Users, UserCheck, Store, ShoppingCart } from 'lucide-react';
import { StatCard, AnimatedNumber } from '@/components/ui';
import { AdminDashboard } from './types';
import { formatNumber } from './format';

interface AdminDashboardCardsProps {
  dashboard: AdminDashboard | null;
  loading: boolean;
}

export function AdminDashboardCards({ dashboard, loading }: AdminDashboardCardsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <StatCard
        variant="gradient"
        tone="coral"
        label="Total Users"
        value={loading ? '—' : <AnimatedNumber value={dashboard?.users.total ?? 0} />}
        icon={<Users className="w-5 h-5" />}
        footnote={dashboard ? `${dashboard.users.active} active` : undefined}
        loading={loading}
      />
      <StatCard
        tone="violet"
        label="Active Stores"
        value={loading ? '—' : dashboard?.stores.active ?? 0}
        icon={<Store className="w-5 h-5" />}
        footnote={dashboard ? `${dashboard.stores.total} total` : undefined}
        loading={loading}
      />
      <StatCard
        tone="teal"
        label="Units Sold Today"
        value={loading ? '—' : <AnimatedNumber value={dashboard?.today.total_sales ?? 0} formatter={formatNumber} flashOnChange />}
        icon={<ShoppingCart className="w-5 h-5" />}
        footnote={dashboard ? `${dashboard.today.active_stores} stores trading` : undefined}
        loading={loading}
      />
      <StatCard
        tone="amber"
        label="Distinct Items Today"
        value={loading ? '—' : <AnimatedNumber value={dashboard?.today.items_sold ?? 0} formatter={formatNumber} flashOnChange />}
        icon={<UserCheck className="w-5 h-5" />}
        footnote="Unique SKUs sold"
        loading={loading}
      />
    </div>
  );
}
