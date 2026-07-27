'use client';

/**
 * Cannibalization — did the promotion create demand, or just move it?
 *
 * THE QUESTION THIS ANSWERS, AND WHY IT HAS A TAB. For retention, a promotion
 * that shifts volume between own SKUs is a modelling refinement. For a
 * supplier-funded promotion it is the CENTRAL question: a supplier will not pay
 * for volume stolen from their own other SKU. This surface shows, per promoted
 * SKU, how much of the lift was genuinely new category demand versus taken from
 * neighbours — the number the settlement on the Trade tab is computed from.
 *
 * THE METHOD, STATED PLAINLY FOR THE USER. Difference-in-differences: the
 * promoted SKU's lift (treated vs control) minus the whole category's lift. If
 * the SKU rose more than its category, the gap came from other products. A
 * small control arm makes this directional, and the UI says so rather than
 * dressing a weak estimate as a decisive one.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, GitMerge, RefreshCw } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TableBody, TableHead, TableRow, Td, Th,
} from '@/components/ui';
import { Reveal, Stagger, StaggerItem, SyntheticBadge } from '@/components/flywheel/motion';
import { aed, fetchCampaigns, fetchCannibalization, recomputeCannibalization } from '@/lib/flywheel';
import type { CampaignSummary, CannibalizationResult } from '@/types/flywheel';

/** Bar showing incremental (green) vs cannibalized (amber) share of the lift. */
function LiftSplit({ promoted, cannibalized }: { promoted: number; cannibalized: number }) {
  if (promoted <= 0) {
    return <div className="text-xs text-ink-muted italic">no measurable lift</div>;
  }
  const cannPct = Math.min(100, Math.round((cannibalized / promoted) * 100));
  const incPct = 100 - cannPct;
  return (
    <div className="w-full">
      <div className="flex h-5 rounded overflow-hidden bg-surface-2">
        <div className="bg-signal-up" style={{ width: `${incPct}%` }} title="incremental" />
        <div className="bg-amber-500" style={{ width: `${cannPct}%` }} title="cannibalized" />
      </div>
      <div className="flex justify-between text-[11px] text-ink-muted mt-1">
        <span>{incPct}% new demand</span>
        <span>{cannPct}% moved from category</span>
      </div>
    </div>
  );
}

export default function CannibalizationPage() {
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [data, setData] = useState<CannibalizationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const c = await fetchCampaigns();
      const list = c?.campaigns ?? [];
      setCampaigns(list);
      if (list.length && selected === null) setSelected(list[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load campaigns');
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    (async () => {
      try { const d = await fetchCannibalization(selected); if (!cancelled) setData(d); }
      catch { if (!cancelled) setData(null); }
    })();
    return () => { cancelled = true; };
  }, [selected]);

  const recompute = async () => {
    if (selected === null) return;
    setBusy(true);
    try { await recomputeCannibalization(selected); setData(await fetchCannibalization(selected)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Recompute failed'); }
    finally { setBusy(false); }
  };

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-80" /></div>;
  }
  if (error && !campaigns.length) {
    return <div className="p-6"><ErrorState title="Cannibalization unavailable" description={error} onRetry={load} /></div>;
  }

  const rows = data?.results ?? [];

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel · Track B"
        title="Cannibalization"
        description="How much of a promoted SKU's lift was new category demand versus volume taken from its neighbours. The basis a supplier is honestly charged on."
        icon={<GitMerge className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <SyntheticBadge />
            <Button variant="ghost" onClick={load} aria-label="Refresh">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        }
      />

      <div className="flex flex-wrap gap-2 mb-4">
        {campaigns.map((c) => (
          <Button key={c.id} size="sm"
            variant={selected === c.id ? 'primary' : 'ghost'}
            onClick={() => setSelected(c.id)}>{c.name}</Button>
        ))}
      </div>

      <Reveal>
        <Card padding="lg">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <h3 className="font-medium">Promoted-SKU lift, split by source</h3>
              <p className="text-sm text-ink-muted">
                Difference-in-differences: promoted-SKU lift minus category lift, treatment vs control.
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={recompute} disabled={busy}>
              {busy ? 'Computing…' : 'Recompute now'}
            </Button>
          </div>

          {rows.length === 0 ? (
            <EmptyState title="No cannibalization readout yet"
              description="Recompute to estimate it, or wait for the next scheduled pass. Needs a promoted SKU and both arms." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHead>
                  <TableRow>
                    <Th>Category / SKU</Th><Th>Promoted lift</Th><Th>Category net</Th>
                    <Th>Source of lift</Th><Th>Net incremental margin</Th><Th>Confidence</Th>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((r, i) => (
                    <TableRow key={`${r.promoted_item_id}-${i}`}>
                      <Td>
                        <div className="font-medium">{r.category}</div>
                        <div className="text-xs text-ink-muted">SKU {r.promoted_item_id ?? '—'}</div>
                      </Td>
                      <Td className="tabular-nums">{r.promoted_lift_units}</Td>
                      <Td className="tabular-nums">{r.category_net_lift_units}</Td>
                      <Td className="w-56">
                        <LiftSplit promoted={r.promoted_lift_units} cannibalized={r.cannibalized_units} />
                      </Td>
                      <Td className="tabular-nums">{aed(r.net_incremental_margin_aed)}</Td>
                      <Td>
                        {r.is_reliable
                          ? <Badge variant="success">reliable</Badge>
                          : <Badge variant="amber">directional</Badge>}
                      </Td>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          {rows.some((r) => r.cannibalized_units > 0) ? (
            <div className="mt-4 flex items-start gap-2 text-sm text-amber-600">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>
                Some lift was cannibalized from the category. A supplier is charged only on the
                genuinely incremental category units, never the gross promoted lift.
              </span>
            </div>
          ) : null}

          {rows.length > 0 ? (
            <div className="mt-4 pt-4 border-t border-line space-y-2">
              {rows.map((r, i) => (
                <p key={i} className="text-xs text-ink-muted">
                  <span className="font-medium text-ink">{r.category}:</span> {r.note}
                </p>
              ))}
            </div>
          ) : null}
        </Card>
      </Reveal>
    </div>
  );
}
