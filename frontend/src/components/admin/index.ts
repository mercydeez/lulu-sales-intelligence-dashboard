import dynamic from 'next/dynamic';
import { createElement } from 'react';
import { Skeleton } from '@/components/ui';

export { AdminDashboardCards } from './AdminDashboardCards';
// Recharts-backed — split into an async chunk so it stays out of the admin
// route's First-Load JS (loads when the trend chart mounts).
export const AdminTrendChart = dynamic(
  () => import('./AdminTrendChart').then((m) => m.AdminTrendChart),
  { ssr: false, loading: () => createElement(Skeleton, { className: 'h-72 w-full rounded-2xl' }) },
);
export { UsersTable } from './UsersTable';
export { StoresTable } from './StoresTable';
export { ActivityFeed } from './ActivityFeed';
export { NewUserModal } from './NewUserModal';
export type { AdminUser, AdminStore, ActivityItem, AdminDashboard, AdminTab } from './types';
