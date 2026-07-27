import dynamic from 'next/dynamic';
import { createElement } from 'react';
import { Skeleton } from '@/components/ui';

export { EmployeeSummaryCards } from './EmployeeSummaryCards';
export { EmployeeBioCard } from './EmployeeBioCard';
export { RolePerformanceTable } from './RolePerformanceTable';
export { RoleDistribution } from './RoleDistribution';
export { EmployeeFilters } from './EmployeeFilters';
export { EmployeeListView } from './EmployeeListView';
// Recharts-backed — split into an async chunk so the employees route (which
// renders several of these inline) doesn't ship Recharts in its First-Load JS.
export const EmployeePerformanceChart = dynamic(
  () => import('./EmployeePerformanceChart').then((m) => m.EmployeePerformanceChart),
  { ssr: false, loading: () => createElement(Skeleton, { className: 'h-64 w-full rounded-2xl' }) },
);
export { EmployeeFormModal } from './EmployeeFormModal';
export { EmployeeDetailModal } from './EmployeeDetailModal';
export { ROLE_LABELS, roleLabel } from './format';
export type {
  Employee, EmployeeSummary, RoleAnalytics, EmployeePerformance,
  PerformanceChartData, EmployeeViewMode, EmployeeTab,
} from './types';
