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

/** COLORBLIND-SAFE categorical hues — the Wong palette (Nature Methods 2011)
 * with series-1 kept as the brand teal. Chosen so the sequence stays distinct
 * under protanopia/deuteranopia/tritanopia; the common actual-vs-forecast pair
 * (1 vs 2) is teal↔orange, distinguishable under every CVD type. Always pair
 * colour with a second channel (dash/marker/pattern) — never colour alone
 * (WCAG 1.4.1).
 *
 * These resolve through the CSS `--series-*` vars so every chart follows the
 * active theme (globals.css defines light values + brightened dark values)
 * with no JS re-render. CSS vars are valid in SVG fill/stroke/stopColor —
 * do NOT string-manipulate these (no `+ '33'` alpha suffixes); use
 * stopOpacity/fillOpacity props for transparency instead. */
export const CHART_SERIES = [
  'var(--series-1)', // brand teal (anchor)
  'var(--series-2)', // orange
  'var(--series-3)', // blue
  'var(--series-4)', // vermillion
  'var(--series-5)', // reddish-purple
  'var(--series-6)', // sky blue
  'var(--series-7)', // gold / yellow
  'var(--series-8)', // grey
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
 * Named chart colours by SEMANTIC ROLE (stable API for consumers). The keys are
 * legacy names; they now resolve to the colorblind-safe Wong palette (see
 * CHART_SERIES) — e.g. `violet` is the 2nd series (orange) used for
 * forecast/predicted, `coral` is the 4th (vermillion) reserved for
 * attention/returns. Keep referencing by role; the underlying hue is CVD-safe.
 */
export const CHART = {
  teal: CHART_SERIES[0],   // brand / primary series (sales, actual) — teal
  violet: CHART_SERIES[1], // forecast / predicted — Wong orange
  amber: CHART_SERIES[2],  // secondary — Wong blue
  coral: CHART_SERIES[3],  // attention / returns ONLY — Wong vermillion
  blue: CHART_SERIES[4],   // Wong reddish-purple
  emerald: CHART_SERIES[5],// Wong sky blue
  pink: CHART_SERIES[6],   // gold
  slate: CHART_SERIES[7],  // grey
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

/* ────────────────────────────────────────────────────────────────────────────
 * Shared layout contract (alignment).
 *
 * Colors above make charts LOOK the same; these make them SIT the same. Every
 * chart hand-rolling its own margin/axis width is how sibling cards end up with
 * plot edges that don't line up and labels that clip. Use these everywhere:
 *   <AreaChart margin={CHART_MARGIN}> … <YAxis width={Y_AXIS_WIDTH} …>
 * ──────────────────────────────────────────────────────────────────────────── */

/** Standard cartesian margin — same top/right breathing room on every chart. */
export const CHART_MARGIN = { top: 8, right: 12, left: 0, bottom: 0 } as const;

/** For charts that draw a top-positioned label (e.g. a ReferenceLine with
 * `position: 'top'`): reserves headroom so the label isn't clipped. */
export const CHART_MARGIN_LABELED = { top: 24, right: 12, left: 0, bottom: 0 } as const;

/** Horizontal (layout="vertical") bar charts — extra right so end ticks fit. */
export const HBAR_MARGIN = { top: 4, right: 24, left: 8, bottom: 4 } as const;

/** Numeric Y axis width — one gutter for every cartesian chart so sibling
 * cards' plot areas start at the same x. Fits "180.0K" at fontSize 12. */
export const Y_AXIS_WIDTH = 48;

/** Category Y axis width for horizontal bar charts (item/store names). Pair
 * with a single-line label formatter — wrapped ticks collide at 10+ rows. */
export const Y_AXIS_CATEGORY_WIDTH = 150;

/** Height for a horizontal bar chart that keeps rows readable (no tick
 * collision): ~28px per row + axis. */
export const hbarHeight = (rows: number, min = 280) => Math.max(min, rows * 28 + 40);

/**
 * Cap a categorical series at `n` slices + an aggregated "Other". An 8-hue
 * palette cannot encode 20+ categories (colors repeat and the legend overflows
 * its card); 7 + Other = exactly one palette cycle and a 2-row legend.
 * `sumKeys` are extra numeric fields to aggregate into the Other row (e.g. the
 * revenue field a tooltip reads).
 */
export function topNWithOther<T extends object>(
  data: T[],
  n: number,
  valueKey: keyof T & string,
  nameKey: keyof T & string,
  sumKeys: (keyof T & string)[] = [],
  otherLabel = 'Other',
): T[] {
  if (data.length <= n + 1) return data;
  const val = (row: T, key: string) => Number((row as Record<string, unknown>)[key]);
  const sorted = [...data].sort((a, b) => val(b, valueKey) - val(a, valueKey));
  const rest = sorted.slice(n);
  const other = { ...rest[0], [nameKey]: otherLabel } as Record<string, unknown>;
  for (const k of [valueKey, ...sumKeys]) {
    other[k] = rest.reduce((s, r) => s + (val(r, k) || 0), 0);
  }
  return [...sorted.slice(0, n), other as T];
}
