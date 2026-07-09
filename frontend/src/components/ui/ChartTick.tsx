'use client';

/**
 * Recharts wraps a category-axis tick onto a second <tspan> whenever the
 * label's RENDERED PIXEL WIDTH exceeds the tick's slot — independent of any
 * `tickFormatter` string-length truncation. A wrapped tick is twice as tall as
 * its neighbors, so on a fixed-height row grid it reads as a misaligned,
 * squished-together label (Recharts also drops the inter-word space when it
 * measures the wrap point, e.g. "Rainbow Evaporate…" renders as
 * "RainbowEvaporate…"). Truncating the string more aggressively just moves the
 * pixel threshold; it doesn't remove Recharts' own wrap behavior.
 *
 * The fix is a custom tick renderer: providing `tick={singleLineTick(fmt)}`
 * fully replaces Recharts' tick component, so its wrap logic never runs —
 * we render exactly the formatter's output as one <text> node, guaranteed
 * single-line, matching neighboring rows' height.
 */
interface TickProps {
  x?: number;
  y?: number;
  payload?: { value: string | number };
}

export function singleLineTick(
  formatter: (value: string) => string,
  opts: { fontSize?: number; fill?: string; textAnchor?: 'end' | 'start' | 'middle' } = {},
) {
  const { fontSize = 11, fill = 'var(--chart-text)', textAnchor = 'end' } = opts;
  function SingleLineTick({ x = 0, y = 0, payload }: TickProps) {
    return (
      <text x={x} y={y} dy={4} textAnchor={textAnchor} fontSize={fontSize} fill={fill}>
        {payload ? formatter(String(payload.value)) : ''}
      </text>
    );
  }
  return SingleLineTick;
}
