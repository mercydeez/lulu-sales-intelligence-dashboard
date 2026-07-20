'use client';

/**
 * CFO / Budget dashboard (§20.4).
 *
 * Allocated → reserved → committed → spent → released, the full append-only
 * ledger, and cash requirement by date.
 *
 * A NOTE ON THE NUMBERS: every amount here is rendered from the string the API
 * returned. Nothing on this page is summed, divided or otherwise recomputed in
 * JavaScript — a CFO dashboard that does float arithmetic on a ledger is a
 * dashboard that eventually disagrees with the ledger. The one derived figure
 * (the utilisation bar) is a visual proportion, never a reported number.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw, Wallet } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TableBody, TableHead, TableRow, Td, Th,
} from '@/components/ui';
import { Reveal, Stagger, StaggerItem, SyntheticBadge } from '@/components/flywheel/motion';
import { aed, fetchBudget } from '@/lib/flywheel';
import type { BudgetOverview } from '@/types/flywheel';

const ENTRY_TONE: Record<string, 'neutral' | 'teal' | 'amber' | 'success' | 'danger' | 'violet'> = {
  ALLOCATED: 'neutral', RESERVED: 'amber', COMMITTED: 'violet',
  SPENT: 'danger', RELEASED: 'success',
};

export default function BudgetDashboard() {
  const [data, setData] = useState<BudgetOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try { setData(await fetchBudget()); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load budgets'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-80" /></div>;
  }
  if (error) {
    return <div className="p-6"><ErrorState title="Budgets unavailable" description={error} onRetry={load} /></div>;
  }

  const budgets = data?.budgets ?? [];

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel"
        title="Budget & exposure"
        description="Postgres is the financial source of truth. Every movement below is an append-only ledger entry with its before and after balance."
        icon={<Wallet className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <SyntheticBadge />
            <Button variant="ghost" onClick={load} aria-label="Refresh"><RefreshCw className="w-4 h-4" /></Button>
          </div>
        }
      />

      {budgets.length === 0 ? (
        <Card padding="lg">
          <EmptyState title="No active budget periods"
                      description="Budgets are seeded per quarter. Run the Flywheel migration to create the demo allocations." />
        </Card>
      ) : (
        <Stagger className="grid gap-4 lg:grid-cols-3 mb-6">
          {budgets.map((budget) => {
            const allocated = Number.parseFloat(budget.allocated_aed) || 0;
            const reserved = Number.parseFloat(budget.reserved_aed) || 0;
            const spent = Number.parseFloat(budget.spent_aed) || 0;
            // Visual proportions only — never displayed as a figure.
            const spentPct = allocated > 0 ? Math.min(100, (spent / allocated) * 100) : 0;
            const reservedPct = allocated > 0 ? Math.min(100 - spentPct, (reserved / allocated) * 100) : 0;
            const tight = allocated > 0 && (spent + reserved) / allocated > 0.9;

            return (
              <StaggerItem key={budget.budget_id}>
                <Card padding="lg" className="h-full">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {budget.budget_type.replace(/_/g, ' ')}
                      </h2>
                      <p className="text-[11px] text-slate-500">
                        {budget.period_start} → {budget.period_end}
                      </p>
                    </div>
                    {tight && (
                      <Badge variant="danger">
                        <AlertTriangle className="w-3 h-3 mr-1" />tight
                      </Badge>
                    )}
                  </div>

                  <p className="mt-4 font-mono text-2xl text-slate-900 dark:text-slate-100">
                    {aed(budget.available_aed)}
                  </p>
                  <p className="text-xs text-slate-500">
                    available of {aed(budget.allocated_aed)} {budget.currency}
                  </p>

                  {/* Stacked utilisation bar: spent, then reserved, then free. */}
                  <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"
                       role="img"
                       aria-label={`${aed(budget.spent_aed)} spent and ${aed(budget.reserved_aed)} reserved of ${aed(budget.allocated_aed)} allocated`}>
                    <div className="bg-rose-500 transition-[width] duration-500" style={{ width: `${spentPct}%` }} />
                    <div className="bg-amber-400 transition-[width] duration-500" style={{ width: `${reservedPct}%` }} />
                  </div>

                  <dl className="mt-4 space-y-1.5 text-xs">
                    {([
                      ['Reserved', budget.reserved_aed, 'text-amber-700 dark:text-amber-400'],
                      ['Committed', budget.committed_aed, 'text-violet-700 dark:text-violet-400'],
                      ['Spent', budget.spent_aed, 'text-rose-700 dark:text-rose-400'],
                      ['Released', budget.released_aed, 'text-teal-700 dark:text-teal-300'],
                    ] as const).map(([label, value, tone]) => (
                      <div key={label} className="flex justify-between">
                        <dt className="text-slate-500">{label}</dt>
                        <dd className={`font-mono tabular-nums ${tone}`}>{aed(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </Card>
              </StaggerItem>
            );
          })}
        </Stagger>
      )}

      {(data?.cash_requirement_by_date.length ?? 0) > 0 && (
        <Reveal>
          <Card padding="lg" className="mb-6">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Cash requirement by date
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              When approved procurement actually needs funding.
            </p>
            <ul className="mt-4 flex flex-wrap gap-3">
              {data!.cash_requirement_by_date.map((row) => (
                <li key={row.date}
                    className="rounded-lg border border-slate-200 px-4 py-3 dark:border-slate-700">
                  <p className="font-mono text-lg text-slate-900 dark:text-slate-100">
                    {aed(row.amount_aed, { compact: true })}
                  </p>
                  <p className="text-[11px] text-slate-500">{row.date}</p>
                </li>
              ))}
            </ul>
          </Card>
        </Reveal>
      )}

      <Reveal delay={0.05}>
        <Card padding="lg">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Ledger</h2>
          <p className="mt-1 text-xs text-slate-500">
            Append-only. Each row records the balance before and after, so any figure on this page
            can be traced back to the movements that produced it.
          </p>

          {(data?.ledger.length ?? 0) === 0 ? (
            <p className="mt-6 text-sm text-slate-500">
              No movements yet — approve and activate a campaign to reserve budget.
            </p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <Table>
                <TableHead>
                  <TableRow>
                    <Th>When</Th><Th>Type</Th><Th>Amount</Th>
                    <Th>Balance before → after</Th><Th>Campaign</Th><Th>Reason</Th>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {data!.ledger.map((entry, i) => (
                    <TableRow key={`${entry.at}-${i}`}>
                      <Td className="whitespace-nowrap text-xs text-slate-500">
                        {new Date(entry.at).toLocaleString()}
                      </Td>
                      <Td><Badge variant={ENTRY_TONE[entry.entry_type] ?? 'neutral'}>
                        {entry.entry_type.toLowerCase()}
                      </Badge></Td>
                      <Td className="font-mono tabular-nums">{aed(entry.amount_aed)}</Td>
                      <Td className="font-mono text-xs tabular-nums text-slate-500">
                        {aed(entry.balance_before)} → {aed(entry.balance_after)}
                      </Td>
                      <Td className="text-xs">{entry.campaign ?? '—'}</Td>
                      <Td className="max-w-xs truncate text-xs text-slate-500" title={entry.reason ?? ''}>
                        {entry.reason ?? '—'}
                      </Td>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </Card>
      </Reveal>
    </div>
  );
}
