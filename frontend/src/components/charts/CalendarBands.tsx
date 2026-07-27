/**
 * Ramadan/DSF/Eid shading bands for time-axis charts (E4-7).
 *
 * Usage inside any Recharts chart whose XAxis dataKey is an ISO date string:
 *
 *   const calendar = useUaeCalendar();
 *   <AreaChart data={data}>
 *     {calendarBands(calendar, data.map((d) => d.date))}
 *     ...
 *
 * Render the bands FIRST so they sit behind grid/series. Bands are clipped to
 * the chart's actual date domain (categorical axes need real tick values);
 * events with no overlap produce nothing, so charts on short windows stay
 * clean. Pure and theme-following (amber channel at whisper opacity).
 */
import { ReferenceArea } from 'recharts';
import type { ReactElement } from 'react';
import type { UaeCalendarEvent } from '@/hooks/useUaeCalendar';

/** Label only bands spanning at least this many points — thin slivers stay quiet. */
const LABEL_MIN_POINTS = 4;

export function calendarBands(
  events: UaeCalendarEvent[],
  dates: string[],
): ReactElement[] {
  if (!events.length || dates.length < 2) return [];

  // Dates arrive chart-ordered (ascending). Clip each event to the domain.
  const first = dates[0];
  const last = dates[dates.length - 1];

  return events.flatMap((ev) => {
    if (ev.end < first || ev.start > last) return []; // no overlap
    const x1 = dates.find((d) => d >= ev.start) ?? first;
    // findLast isn't in the ES2017 lib target — reverse-scan manually.
    let x2 = last;
    for (let i = dates.length - 1; i >= 0; i--) {
      if (dates[i] <= ev.end) { x2 = dates[i]; break; }
    }
    if (x1 > x2) return [];

    const span = dates.indexOf(x2) - dates.indexOf(x1);
    return [
      <ReferenceArea
        key={`cal-${ev.key}`}
        x1={x1}
        x2={x2}
        fill="rgb(var(--a-amber))"
        fillOpacity={0.07}
        stroke="none"
        label={
          span >= LABEL_MIN_POINTS
            ? { value: ev.name, position: 'insideTopLeft', fontSize: 10, fill: 'var(--chart-text)' }
            : undefined
        }
      />,
    ];
  });
}
