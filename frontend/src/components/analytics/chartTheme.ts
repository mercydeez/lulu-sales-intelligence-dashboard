// Sunset Pop chart palette + shared Recharts styling for the analytics screen.
// Light-surface friendly: warm grid, ink-muted axes, white tooltip card.

export const SUNSET_COLORS = [
  '#ff6b5c', // coral
  '#2dd4bf', // teal
  '#8b5cf6', // violet
  '#fbbf24', // amber
  '#f43f5e', // rose
  '#38bdf8', // sky
  '#10b981', // emerald
  '#ec4899', // pink
];

export const CHART = {
  coral: '#ff6b5c',
  teal: '#2dd4bf',
  violet: '#8b5cf6',
  amber: '#fbbf24',
  emerald: '#10b981',
  rose: '#f43f5e',
  grid: 'rgba(30, 27, 46, 0.08)',
  axis: '#8b8699',
} as const;

export const tooltipStyle = {
  backgroundColor: '#ffffff',
  border: '1px solid #f1d9d2',
  borderRadius: '12px',
  boxShadow: '0 10px 30px -16px rgba(30, 27, 46, 0.25)',
  color: '#1e1b2e',
} as const;

export const tooltipLabelStyle = { color: '#6b6680', fontWeight: 600 } as const;
