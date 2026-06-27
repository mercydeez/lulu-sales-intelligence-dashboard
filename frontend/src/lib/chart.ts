/**
 * Shared Recharts theming — one source of truth for series colors, axes, grid,
 * and tooltip styling so every chart in the app is color-coded consistently and
 * reads at AA contrast. Mirrors the CSS `--series-*` vars (globals.css) and the
 * Tailwind `series` scale (tailwind.config.js).
 *
 * Usage in a chart:
 *   import { CHART_SERIES, axisProps, gridProps, tooltipStyle, seriesColor } from '@/lib/chart';
 *   <CartesianGrid {...gridProps} />
 *   <XAxis dataKey="label" {...axisProps} />
 *   <Tooltip {...tooltipStyle} />
 *   <Bar dataKey="revenue" fill={seriesColor(0)} radius={[6,6,0,0]} />
 */

/** Distinct, AA-contrast categorical hues (brand teal leads). */
export const CHART_SERIES = [
  '#0f766e', // teal (brand)
  '#6d49cf', // violet
  '#d97706', // amber
  '#c8451f', // coral
  '#2563eb', // blue
  '#0f8f73', // emerald
  '#db2777', // pink
  '#475569', // slate
] as const;

/** Cycle the categorical palette by index. */
export const seriesColor = (i: number) => CHART_SERIES[((i % CHART_SERIES.length) + CHART_SERIES.length) % CHART_SERIES.length];

/** Semantic colors — only ever mean meaning. */
export const SIGNAL = { up: '#0f8f73', down: '#c8451f', neutral: '#5f6660' } as const;

const GRID = '#eceae4';
const AXIS_TEXT = '#5f6660';

/** CartesianGrid props — faint horizontal rules, no vertical clutter. */
export const gridProps = {
  stroke: GRID,
  strokeDasharray: '3 3',
  vertical: false,
} as const;

/** XAxis/YAxis shared props — quiet ticks, no axis line. */
export const axisProps = {
  stroke: AXIS_TEXT,
  tick: { fill: AXIS_TEXT, fontSize: 12 },
  tickLine: false,
  axisLine: false,
} as const;

/** Tooltip style props — clean white card, soft shadow, rounded. */
export const tooltipStyle = {
  cursor: { fill: 'rgba(15,118,110,0.06)' },
  contentStyle: {
    background: '#ffffff',
    border: '1px solid #e6e6e0',
    borderRadius: 12,
    boxShadow: '0 12px 32px -12px rgba(20,29,33,0.30)',
    fontSize: 12,
    padding: '10px 12px',
  },
  labelStyle: { color: '#1a1d21', fontWeight: 600, marginBottom: 4 },
  itemStyle: { color: '#4b5258' },
} as const;

/**
 * Inject an SVG vertical gradient <defs> into an area/bar chart. Returns the id
 * to reference as `fill={`url(#${id})`}`. Render <ChartGradient> (below) once.
 */
export const gradientId = (key: string) => `grad-${key}`;
