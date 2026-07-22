'use client';

/**
 * Trade Promotion — the supplier-funded track (Track B).
 *
 * WHY THIS IS THE ONE PERMITTED NEW SURFACE. The plan holds the line at "no new
 * pages" through Horizons 1–3, with a single ruled exception: the supplier-facing
 * view that the parallel-markets decision (20 Jul 2026) necessarily creates. A
 * supplier funds a promotion of their SKUs and is owed a view of what their money
 * bought — and only their money, only their SKUs.
 *
 * THE NUMBER THAT MATTERS. Every settlement here rests on measured, causal,
 * CANNIBALIZATION-ADJUSTED performance: a supplier pays only for demand the
 * promotion genuinely created, never for volume moved from their own other SKU.
 * That is the difference between a trade-promotion tool a supplier trusts and one
 * they dispute — and it is why the Cannibalization tab sits next to this one.
 *
 * CONFIDENTIALITY. The supplier drill-down is scoped to a supplier's funded SKUs.
 * The overview here is the RETAILER's cross-supplier view; the supplier's own
 * view (one supplier, their fundings only) is the /suppliers/{id}/dashboard
 * endpoint, surfaced by selecting a supplier.
 */
import { useCallback, useEffect, useState } from 'react';
import { Coins, RefreshCw, ShieldCheck } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TableBody, TableHead, TableRow, Td, Th,
} from '@/components/ui';
import { Reveal, SyntheticBadge } from '@/components/flywheel/motion';
import {
  aed, fetchSupplierDashboard, fetchTradeOverview, FUNDING_TONE,
} from '@/lib/flywheel';
import type { SupplierDashboard, TradeOverview } from '@/types/flywheel';

const FUNDING_LABEL: Record<string, string> = {
  co_op: 'Co-op (cost share)',
  scan_down: 'Scan-down (per-unit rebate)',
  fixed_fee: 'Fixed trade fee',
};

export default function TradePromotionPage() {
  const [overview, setOverview] = useState<TradeOverview | null>(null);
  const [selectedSupplier, setSelectedSupplier] = useState<number | null>(null);
  const [dashboard, setDashboard] = useState<SupplierDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try { setOverview(await fetchTradeOverview()); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load trade promotions'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (selectedSupplier === null) { setDashboard(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const d = await fetchSupplierDashboard(selectedSupplier);
        if (!cancelled) setDashboard(d);
      } catch { if (!cancelled) setDashboard(null); }
    })();
    return () => { cancelled = true; };
  }, [selectedSupplier]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-80" /></div>;
  }
  if (error) {
    return <div className="p-6"><ErrorState title="Trade promotion unavailable" description={error} onRetry={load} /></div>;
  }

  const fundings = overview?.fundings ?? [];
  const suppliers = Array.from(
    new Map(fundings.map((f) => [f.supplier_id, f.supplier_name])).entries());

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel · Track B"
        title="Trade promotion"
        description="Supplier-funded promotions, settled on measured, cannibalization-adjusted incremental performance. A supplier pays only for demand the promotion genuinely created."
        icon={<Coins className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <SyntheticBadge />
            <Button variant="ghost" onClick={load} aria-label="Refresh">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        }
      />

      <Reveal>
        <Card padding="lg" className="mb-6">
          <h3 className="font-medium mb-3">Supplier fundings</h3>
          {fundings.length === 0 ? (
            <EmptyState title="No supplier fundings yet"
              description="Propose a funding on a campaign to begin a supplier-funded promotion." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHead>
                  <TableRow>
                    <Th>Supplier</Th><Th>Campaign</Th><Th>Type</Th><Th>Status</Th>
                    <Th>Committed</Th><Th>Spent</Th><Th>Settled</Th>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {fundings.map((f) => (
                    <TableRow key={f.funding_id}
                      onClick={() => setSelectedSupplier(f.supplier_id)}
                      className={`cursor-pointer ${selectedSupplier === f.supplier_id ? 'bg-surface-2' : ''}`}>
                      <Td className="font-medium">{f.supplier_name}</Td>
                      <Td>{f.campaign_name}</Td>
                      <Td className="text-ink-muted">{FUNDING_LABEL[f.funding_type] ?? f.funding_type}</Td>
                      <Td><Badge variant={FUNDING_TONE[f.status] ?? 'neutral'}>{f.status}</Badge></Td>
                      <Td className="tabular-nums">{aed(f.committed_aed)}</Td>
                      <Td className="tabular-nums">{aed(f.spent_aed)}</Td>
                      <Td className="tabular-nums">{aed(f.settled_aed)}</Td>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          <p className="text-xs text-ink-muted mt-3">{overview?.note}</p>
        </Card>
      </Reveal>

      {suppliers.length > 0 ? (
        <>
          <div className="flex flex-wrap gap-2 mb-4">
            <span className="text-sm text-ink-muted self-center me-2">Supplier view:</span>
            {suppliers.map(([id, name]) => (
              <Button key={id} size="sm"
                variant={selectedSupplier === id ? 'primary' : 'ghost'}
                onClick={() => setSelectedSupplier(id)}>{name}</Button>
            ))}
          </div>

          {/* Reveal (not StaggerItem): this card is rendered on click, after the
              page's Stagger has already orchestrated, so it must self-animate.
              Keyed by supplier so it re-reveals each time the selection changes. */}
          {dashboard ? (
            <Reveal key={selectedSupplier ?? 'none'}>
              <Card padding="lg">
                <div className="flex items-start justify-between gap-4 mb-4">
                  <div>
                    <h3 className="font-medium">What this supplier sees</h3>
                    <p className="text-sm text-ink-muted">
                      {dashboard.funded_sku_count} funded SKU(s). Committed{' '}
                      {aed(dashboard.totals.committed_aed)} AED · settled{' '}
                      {aed(dashboard.totals.settled_aed)} AED.
                    </p>
                  </div>
                  <Badge variant="teal">
                    <ShieldCheck className="w-3 h-3 me-1 inline" />scoped to their SKUs
                  </Badge>
                </div>

                {dashboard.fundings.map((f) => (
                  <div key={f.funding_id} className="rounded-lg border border-line p-4 mb-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium">{f.campaign_name}</span>
                      <Badge variant={FUNDING_TONE[f.status] ?? 'neutral'}>{f.status}</Badge>
                    </div>
                    {f.settlements.length === 0 ? (
                      <p className="text-sm text-ink-muted">No settlements issued yet.</p>
                    ) : (
                      <Table>
                        <TableHead>
                          <TableRow>
                            <Th>Period</Th><Th>Incremental units</Th>
                            <Th>Incremental margin</Th><Th>Amount due</Th><Th>Status</Th>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {f.settlements.map((s) => (
                            <TableRow key={s.settlement_id}>
                              <Td className="tabular-nums">{s.period.from} → {s.period.to}</Td>
                              <Td className="tabular-nums">{s.incremental_units}</Td>
                              <Td className="tabular-nums">{aed(s.incremental_margin_aed)}</Td>
                              <Td className="tabular-nums font-medium">{aed(s.amount_due_aed)}</Td>
                              <Td><Badge variant={s.status === 'disputed' ? 'danger' : 'neutral'}>{s.status}</Badge></Td>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </div>
                ))}

                <div className="mt-2 flex items-start gap-2 text-xs text-ink-muted">
                  <ShieldCheck className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>{dashboard.confidentiality_note}</span>
                </div>
              </Card>
            </Reveal>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
