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

/** Distinct, AA-contrast categorical hues (brand teal leads).
 *
 * These resolve through the CSS `--series-*` vars so every chart follows the
 * active theme (globals.css defines light values + brightened dark values)
 * with no JS re-render. CSS vars are valid in SVG fill/stroke/stopColor —
 * do NOT string-manipulate these (no `+ '33'` alpha suffixes); use
 * stopOpacity/fillOpacity props for transparency instead. */
export const CHART_SERIES = [
  'var(--series-1)', // teal (brand)
  'var(--series-2)', // violet
  'var(--series-3)', // amber
  'var(--series-4)', // coral
  'var(--series-5)', // blue
  'var(--series-6)', // emerald
  'var(--series-7)', // pink
  'var(--series-8)', // slate
] as const;

/** Cycle the categorical palette by index. */
export const seriesColor = (i: number) => CHART_SERIES[((i % CHART_SERIES.length) + CHART_SERIES.length) % CHART_SERIES.length];

/** Semantic colors — only ever mean meaning. Theme-following via CSS vars. */
export const SIGNAL = {
  up: 'var(--signal-up)',
  down: 'var(--signal-down)',
  neutral: 'var(--signal-neutral)',
} as const;

const GRID = 'var(--chart-grid)';
const AXIS_TEXT = 'var(--chart-text)';

/**
 * Brand-aligned named chart colors. Replaces the retired
 * `components/analytics/chartTheme.ts` ("Sunset Pop") palette. Teal leads as the
 * primary/brand hue; coral is reserved for attention/returns signals only.
 */
export const CHART = {
  teal: CHART_SERIES[0],   // brand / primary series (sales, actual)
  violet: CHART_SERIES[1], // forecast / predicted
  amber: CHART_SERIES[2],  // secondary
  coral: CHART_SERIES[3],  // attention / returns ONLY
  blue: CHART_SERIES[4],
  emerald: CHART_SERIES[5],
  pink: CHART_SERIES[6],
  slate: CHART_SERIES[7],
  grid: GRID,
  axis: AXIS_TEXT,
} as const;

/**
 * Categorical fill cycle for donuts/bars. Brand-aligned alias of CHART_SERIES
 * (the old `SUNSET_COLORS` name is gone — import this instead).
 */
export const CATEGORICAL = CHART_SERIES;

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

/** Tooltip style props — clean themed card, soft shadow, rounded. */
export const tooltipStyle = {
  cursor: { fill: 'rgb(var(--a-teal) / 0.06)' },
  contentStyle: {
    background: 'var(--chart-tooltip-bg)',
    border: '1px solid var(--chart-tooltip-border)',
    borderRadius: 12,
    boxShadow: '0 12px 32px -12px var(--shadow-color)',
    fontSize: 12,
    padding: '10px 12px',
  },
  labelStyle: { color: 'var(--text-primary)', fontWeight: 600, marginBottom: 4 },
  itemStyle: { color: 'var(--text-secondary)' },
} as const;

/**
 * Flat tooltip styles for charts that pass them individually
 * (`contentStyle={tooltipContent} labelStyle={tooltipLabelStyle}`) rather than
 * spreading `{...tooltipStyle}`. Same visual language, different call site.
 */
export const tooltipContent = tooltipStyle.contentStyle;
export const tooltipLabelStyle = tooltipStyle.labelStyle;

/**
 * Inject an SVG vertical gradient <defs> into an area/bar chart. Returns the id
 * to reference as `fill={`url(#${id})`}`. Render <ChartGradient> (below) once.
 */
export const gradientId = (key: string) => `grad-${key}`;
