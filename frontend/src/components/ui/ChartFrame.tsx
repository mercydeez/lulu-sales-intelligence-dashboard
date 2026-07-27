'use client';

import { HTMLAttributes, ReactNode, useState } from 'react';
import { motion } from 'framer-motion';
import { Table2, BarChart3 } from 'lucide-react';
import { cn } from '@/lib/cn';
import { Card } from './Card';
import { LiveIndicator } from './LiveIndicator';
import { Skeleton } from './Skeleton';
import { EmptyState } from './EmptyState';

/** Accessible data-table alternative for a chart (WCAG 1.1.1 / 1.4.1). When
 *  provided, ChartFrame renders a "Table" toggle that swaps the SVG for a real
 *  <table> screen readers and keyboard users can consume. */
export interface ChartTableData {
  columns: string[];
  rows: (string | number | null)[][];
  caption?: string;
}

export interface ChartFrameProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  live?: boolean;
  /** Optional accent hue for the title rule (defaults to brand teal). */
  accent?: string;
  height?: number | string;
  loading?: boolean;
  empty?: boolean;
  emptyState?: ReactNode;
  /** Screen-reader description of what the chart shows. Applied as role="img"
   *  + aria-label on the chart region so the SVG isn't an opaque blob to AT. */
  ariaSummary?: string;
  /** Optional tabular equivalent — enables the "view as table" toggle. */
  tableData?: ChartTableData;
  children?: ReactNode;
}

/**
 * Card wrapper for charts — title/actions row, an accent rule, a live badge,
 * loading/empty states, and (opt-in) accessibility: a screen-reader summary and
 * a chart↔table toggle so every chart has a text + data-table alternative.
 * Enters with a subtle rise so dashboards feel alive.
 */
export function ChartFrame({
  title,
  subtitle,
  actions,
  live = false,
  accent = 'var(--brand)',
  height = 300,
  loading = false,
  empty = false,
  emptyState,
  ariaSummary,
  tableData,
  children,
  className,
  ...props
}: ChartFrameProps) {
  const [asTable, setAsTable] = useState(false);
  const canToggle = Boolean(tableData && !loading && !empty);
  const showTable = canToggle && asTable;

  return (
    <motion.div
      variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0 } }}
      className="h-full"
    >
      <Card variant="glass" padding="md" className={cn('h-full', className)} {...props}>
        <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="h-4 w-1 rounded-full"
                style={{ background: accent }}
              />
              <h3 className="text-lg font-semibold text-ink truncate">{title}</h3>
              {live && <LiveIndicator size="sm" />}
            </div>
            {subtitle && <p className="text-sm text-ink-muted mt-0.5 ps-3">{subtitle}</p>}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {actions}
            {canToggle && (
              <button
                type="button"
                onClick={() => setAsTable((v) => !v)}
                aria-pressed={showTable}
                title={showTable ? 'Show chart' : 'View as table'}
                className="inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2 py-1 text-xs text-ink-soft hover:bg-surface-2 transition-colors"
              >
                {showTable ? <BarChart3 className="w-3.5 h-3.5" /> : <Table2 className="w-3.5 h-3.5" />}
                <span className="hidden sm:inline">{showTable ? 'Chart' : 'Table'}</span>
              </button>
            )}
          </div>
        </div>

        <div style={{ height: showTable ? 'auto' : height }}>
          {loading ? (
            <Skeleton width="100%" height="100%" rounded="lg" />
          ) : empty ? (
            emptyState ?? <EmptyState title="No data yet" description="Check back once data starts flowing in." />
          ) : showTable ? (
            <ChartDataTable data={tableData!} />
          ) : (
            // role="img" + aria-label give assistive tech a text alternative for
            // the SVG; the visually-hidden summary also feeds screen readers.
            <div role={ariaSummary ? 'img' : undefined} aria-label={ariaSummary} className="h-full">
              {ariaSummary && <span className="sr-only">{ariaSummary}</span>}
              {children}
            </div>
          )}
        </div>
      </Card>
    </motion.div>
  );
}

/** The accessible <table> alternative rendered by the ChartFrame toggle. */
function ChartDataTable({ data }: { data: ChartTableData }) {
  return (
    <div className="overflow-x-auto max-h-[320px] overflow-y-auto rounded-lg border border-line">
      <table className="w-full text-sm">
        {data.caption && <caption className="sr-only">{data.caption}</caption>}
        <thead className="sticky top-0 bg-surface-2">
          <tr>
            {data.columns.map((c) => (
              <th key={c} scope="col" className="text-start px-3 py-2 font-medium text-ink-soft whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i} className="border-t border-line">
              {row.map((cell, j) => (
                <td key={j} className={cn('px-3 py-1.5 tabular-nums', j === 0 && 'text-ink font-medium')}>
                  {cell ?? '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
