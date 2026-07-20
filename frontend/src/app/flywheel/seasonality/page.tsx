'use client';

/**
 * Seasonality & Shelf-life — the demand context the engine used to ignore.
 *
 * TWO OPERATIONAL TRUTHS ON ONE SURFACE.
 *
 * SEASONALITY. In the GCC, Ramadan roughly doubles grocery demand and the summer
 * lull thins it. A retention offer made before Ramadan is worth more because the
 * customer's forward value genuinely is higher. The demand multiplier here scales
 * that forward value in the EIV calculation, so an offer is valued for the season
 * it is made in — not an average week. It is a stated, auditable calendar an
 * operator maintains, not a forecast.
 *
 * SHELF-LIFE. For a grocer, the most valuable promotion this afternoon may be the
 * yoghurt three days from expiry, not a churn play: clear it now and recover most
 * of its margin, or write off 100% on Thursday. This lists near-expiry stock by
 * value at risk with a recommended markdown — the value the engine was blind to.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CalendarClock, PackageX, RefreshCw } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TableBody, TableHead, TableRow, Td, Th,
} from '@/components/ui';
import { Reveal, Stagger, StaggerItem, SyntheticBadge } from '@/components/flywheel/motion';
import { aed, fetchSeasonality, fetchShelfLife } from '@/lib/flywheel';
import type { SeasonalityCalendar, ShelfLifeResult } from '@/types/flywheel';

/** Multiplier rendered relative to the neutral 1.0 line. */
function FactorBadge({ value }: { value: string }) {
  const n = Number.parseFloat(value);
  const tone = n > 1.05 ? 'success' : n < 0.95 ? 'amber' : 'neutral';
  const arrow = n > 1.05 ? '▲' : n < 0.95 ? '▼' : '—';
  return <Badge variant={tone}>{arrow} {n.toFixed(2)}×</Badge>;
}

export default function SeasonalityPage() {
  const [season, setSeason] = useState<SeasonalityCalendar | null>(null);
  const [shelf, setShelf] = useState<ShelfLifeResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [s, sl] = await Promise.all([fetchSeasonality(), fetchShelfLife()]);
      setSeason(s); setShelf(sl);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load seasonality');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-80" /></div>;
  }
  if (error) {
    return <div className="p-6"><ErrorState title="Seasonality unavailable" description={error} onRetry={load} /></div>;
  }

  const entries = season?.calendar ?? [];
  const candidates = shelf?.candidates ?? [];

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel · Horizon 4"
        title="Seasonality & shelf-life"
        description="The demand context the engine decides within — the season an offer is made in, and the stock that must clear before it expires."
        icon={<CalendarClock className="w-5 h-5" />}
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
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-wide text-[var(--muted)] mb-1">
                Current demand factor
              </div>
              <div className="flex items-center gap-3">
                <span className="text-3xl font-semibold tabular-nums">
                  {Number.parseFloat(season?.current_factor ?? '1').toFixed(2)}×
                </span>
                {season?.active_now?.length ? (
                  <span className="text-sm text-[var(--muted)]">
                    ({season.active_now.map((e) => e.name).join(', ')})
                  </span>
                ) : (
                  <span className="text-sm text-[var(--muted)]">(a normal week)</span>
                )}
              </div>
            </div>
            <p className="text-sm text-[var(--muted)] max-w-md">{season?.note}</p>
          </div>
        </Card>
      </Reveal>

      <Stagger>
        <StaggerItem>
          <Card padding="lg" className="mb-4">
            <h3 className="font-medium mb-3">Seasonality calendar</h3>
            {entries.length === 0 ? (
              <EmptyState title="No seasonality configured"
                description="Migration 080 seeds the UAE calendar (Ramadan, Eid, summer lull)." />
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <Th>Season</Th><Th>Kind</Th><Th>Window</Th>
                      <Th>Demand factor</Th><Th>Status</Th>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {entries.map((e) => (
                      <TableRow key={e.id} className={e.active ? 'bg-[var(--surface-2)]' : ''}>
                        <Td className="font-medium">{e.name}</Td>
                        <Td className="text-[var(--muted)]">{e.kind}</Td>
                        <Td className="tabular-nums text-[var(--muted)]">{e.starts_on} → {e.ends_on}</Td>
                        <Td><FactorBadge value={e.demand_multiplier} /></Td>
                        <Td>{e.active ? <Badge variant="success">active now</Badge> : <Badge variant="neutral">scheduled</Badge>}</Td>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </Card>
        </StaggerItem>

        <StaggerItem>
          <Card padding="lg">
            <div className="flex items-start justify-between gap-4 mb-3">
              <div>
                <h3 className="font-medium flex items-center gap-2">
                  <PackageX className="w-4 h-4 text-[var(--warning)]" /> Near-expiry stock
                </h3>
                <p className="text-sm text-[var(--muted)]">
                  Ranked by value at risk. Clearing this can outrank a retention offer.
                </p>
              </div>
              {shelf?.total_value_at_risk_aed ? (
                <div className="text-right">
                  <div className="text-lg font-semibold tabular-nums">
                    {aed(shelf.total_value_at_risk_aed)} AED
                  </div>
                  <div className="text-xs text-[var(--muted)]">total at risk</div>
                </div>
              ) : null}
            </div>

            {candidates.length === 0 ? (
              <EmptyState title="No near-expiry stock"
                description="No active batches are within the urgent horizon. Nothing to mark down." />
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <Th>Item</Th><Th>Store</Th><Th>Units</Th><Th>Expires</Th>
                      <Th>Days left</Th><Th>Value at risk</Th><Th>Rec. markdown</Th>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {candidates.map((c) => (
                      <TableRow key={c.batch_id}>
                        <Td>
                          <div className="font-medium">{c.item_name}</div>
                          <div className="text-xs text-[var(--muted)]">{c.category} · {c.batch_ref}</div>
                        </Td>
                        <Td className="text-[var(--muted)]">{c.store_name}</Td>
                        <Td className="tabular-nums">{c.units}</Td>
                        <Td className="tabular-nums">{c.expires_on}</Td>
                        <Td>
                          <Badge variant={c.days_to_expiry <= 2 ? 'danger' : 'amber'}>
                            {c.days_to_expiry}d
                          </Badge>
                        </Td>
                        <Td className="tabular-nums font-medium">{aed(c.value_at_risk_aed)}</Td>
                        <Td className="tabular-nums">{Number.parseFloat(c.recommended_markdown_pct).toFixed(0)}%</Td>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}

            {candidates.some((c) => c.days_to_expiry <= 2) ? (
              <div className="mt-4 flex items-start gap-2 text-sm text-[var(--danger)]">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>
                  Some batches expire within two days. A deep markdown now recovers margin that
                  a write-off loses entirely.
                </span>
              </div>
            ) : null}
          </Card>
        </StaggerItem>
      </Stagger>
    </div>
  );
}
