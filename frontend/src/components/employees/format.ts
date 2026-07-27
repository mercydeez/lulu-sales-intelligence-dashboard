import { BadgeVariant } from '@/components/ui';

export const ROLE_LABELS: Record<string, string> = {
  super_admin: 'Super Admin',
  regional_manager: 'Regional Manager',
  store_manager: 'Store Manager',
  inventory_manager: 'Inventory Manager',
  sales_executive: 'Sales Executive',
  customer_service: 'Customer Service',
  cashier: 'Senior Cashier',
  analyst: 'Analyst',
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function gradeVariant(grade?: string): BadgeVariant {
  switch (grade) {
    case 'A+':
    case 'A':
      return 'success';
    case 'B+':
    case 'B':
      return 'teal';
    case 'C':
      return 'warning';
    case 'D':
      return 'amber';
    case 'F':
      return 'danger';
    default:
      return 'neutral';
  }
}

export function statusVariant(status: string): BadgeVariant {
  switch (status) {
    case 'active':
      return 'success';
    case 'on_leave':
      return 'warning';
    case 'terminated':
      return 'danger';
    case 'inactive':
    default:
      return 'neutral';
  }
}

// Dot color for the avatar status indicator.
export const statusDot: Record<string, string> = {
  active: 'bg-emerald-500',
  inactive: 'bg-ink-muted',
  terminated: 'bg-rose-500',
  on_leave: 'bg-amber-500',
};

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-AE', {
    style: 'currency',
    currency: 'AED',
    maximumFractionDigits: 0,
  }).format(value || 0);
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString('en-AE', { year: 'numeric', month: 'short', day: 'numeric' });
}

export function formatMonthYear(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString('en-AE', { month: 'short', year: 'numeric' });
}

export function formatTenure(days: number): string {
  const years = Math.floor(days / 365);
  const months = Math.floor((days % 365) / 30);
  if (years > 0) return `${years}y ${months}m`;
  return `${months}m`;
}

export function getInitials(first: string, last: string): string {
  return `${first.charAt(0)}${last.charAt(0)}`.toUpperCase();
}
