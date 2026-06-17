// Currency/number formatting for the analytics screen.
// The DB `sales` column is units; revenue is `sales * unit_price_aed` (see CLAUDE.md),
// so the analytics endpoints already return AED revenue — we just present it.

export function formatCurrency(value: number): string {
  if (!Number.isFinite(value)) return 'AED 0';
  if (Math.abs(value) >= 1_000_000) return `AED ${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `AED ${(value / 1_000).toFixed(0)}K`;
  return `AED ${Math.round(value)}`;
}

export function formatCompact(value: number): string {
  if (!Number.isFinite(value)) return '0';
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return Math.round(value).toString();
}

export function formatDateShort(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
