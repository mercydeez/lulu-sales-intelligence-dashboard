'use client';

import { Activity, ShoppingCart } from 'lucide-react';
import { Card, SkeletonText, EmptyState } from '@/components/ui';
import { ActivityItem } from './types';
import { formatRelative } from './format';

interface ActivityFeedProps {
  activities: ActivityItem[];
  loading: boolean;
}

export function ActivityFeed({ activities, loading }: ActivityFeedProps) {
  return (
    <Card variant="glass" padding="none">
      <div className="px-5 py-4 border-b border-coral-100 flex items-center gap-2">
        <Activity className="w-5 h-5 text-coral-500" />
        <div>
          <h3 className="text-lg font-semibold text-ink">Recent Activity</h3>
          <p className="text-sm text-ink-muted mt-0.5">Latest sales across the platform</p>
        </div>
      </div>

      {loading ? (
        <div className="p-5"><SkeletonText lines={6} /></div>
      ) : activities.length === 0 ? (
        <EmptyState icon={<Activity className="w-6 h-6" />} title="No recent activity" description="Activity will appear as sales flow in." />
      ) : (
        <ul className="divide-y divide-coral-100/70">
          {activities.map((a, i) => (
            <li key={`${a.timestamp ?? a.date ?? i}-${i}`} className="flex items-center gap-3 p-4">
              <div className="w-9 h-9 rounded-xl bg-teal-100 text-teal-600 flex items-center justify-center shrink-0">
                <ShoppingCart className="w-4 h-4" />
              </div>
              <p className="flex-1 text-sm text-ink-soft">{a.message}</p>
              <span className="text-xs text-ink-muted whitespace-nowrap">{formatRelative(a.timestamp ?? a.date)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
