import { ROLE_DISPLAY_NAMES, UserRole } from '@/types/auth';
import { BadgeVariant } from '@/components/ui';

export function roleLabel(role: string): string {
  return ROLE_DISPLAY_NAMES[role as UserRole] ?? role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

// Tint super_admin/manager roles distinctly; everything else neutral.
export function roleVariant(role: string): BadgeVariant {
  if (role === 'super_admin') return 'violet';
  if (role === 'regional_manager') return 'coral';
  if (role === 'store_manager') return 'teal';
  return 'neutral';
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-AE', {
    style: 'currency',
    currency: 'AED',
    maximumFractionDigits: 0,
  }).format(value || 0);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-AE').format(value || 0);
}

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-AE', { year: 'numeric', month: 'short', day: 'numeric' });
}

export function formatRelative(dateStr: string | null): string {
  if (!dateStr) return 'never';
  const d = new Date(dateStr).getTime();
  if (Number.isNaN(d)) return 'never';
  const diff = Date.now() - d;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(dateStr);
}
