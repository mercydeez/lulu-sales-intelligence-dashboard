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

// Y-axis label for store charts. Store names share a long retailer prefix
// (e.g. "Meridian Hypermarket Deira City Centre"); show the distinguishing part
// after "Hypermarket " so labels don't all read the same and overlap.
export function shortStoreLabel(name: string): string {
  if (!name) return '';
  const marker = 'Hypermarket ';
  const i = name.indexOf(marker);
  const s = i >= 0 ? name.slice(i + marker.length) : name;
  return s.length > 20 ? `${s.slice(0, 19)}…` : s;
}

// Y-axis label for item charts — truncate long product names with an ellipsis.
export function shortItemLabel(name: string): string {
  if (!name) return '';
  return name.length > 22 ? `${name.slice(0, 21)}…` : name;
}

export function formatDateShort(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
