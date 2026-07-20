'use client';

/**
 * Coalition attribution — a retained customer's value is not the retailer's alone.
 *
 * WHY THIS SURFACE EXISTS (the named Horizon-4 surface). Gulf loyalty is
 * coalition-shaped — SHARE, ADNOC, e& Smiles link grocery, fuel, hospitality and
 * travel under one wallet. A customer the grocery campaign "retained" may have
 * been pulled back by fuel points or an upcoming hotel redemption. Claiming 100%
 * of that value for the campaign overstates it and misallocates the next dirham.
 * This shows how a campaign's retained value actually split across the partners
 * the customer engaged with — multi-party attribution, which is table stakes in
 * this market in a way it is not elsewhere.
 *
 * THE WEIGHTS SUM TO ONE. The retailer's own campaign is one partner among them,
 * so the retailer never double-counts value a coalition partner delivered.
 */
import { useCallback, useEffect, useState } from 'react';
import { Network, RefreshCw } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TableBody, TableHead, TableRow, Td, Th,
} from '@/components/ui';
import { Reveal, SyntheticBadge } from '@/components/flywheel/motion';
import { aed, fetchCampaigns, fetchCoalitionAttribution, PARTNER_TONE } from '@/lib/flywheel';
import type { CampaignSummary, CoalitionAttribution } from '@/types/flywheel';

/** Share bar: a partner's fraction of the attributed margin. */
function ShareBar({ weight }: { weight: number | null }) {
  const pct = Math.round((weight ?? 0) * 100);
  return (
    <div className="w-full">
      <div className="h-2 rounded bg-[var(--surface-2)] overflow-hidden">
        <div className="h-full bg-[var(--accent)]" style={{ width: `${pct}%` }} />
      </div>
      <div className="text-[11px] text-[var(--muted)] mt-0.5 tabular-nums">{pct}%</div>
    </div>
  );
}

export default function CoalitionPage() {
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [data, setData] = useState<CoalitionAttribution | null>(null);
  const [loading, setLoading] = useState(true);
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
      try { const d = await fetchCoalitionAttribution(selected); if (!cancelled) setData(d); }
      catch { if (!cancelled) setData(null); }
    })();
    return () => { cancelled = true; };
  }, [selected]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-80" /></div>;
  }
  if (error && !campaigns.length) {
    return <div className="p-6"><ErrorState title="Coalition unavailable" description={error} onRetry={load} /></div>;
  }

  const rows = data?.by_partner ?? [];
  const totalMargin = rows.reduce((sum, r) => sum + Number.parseFloat(r.attributed_margin_aed || '0'), 0);

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel · Horizon 4"
        title="Coalition attribution"
        description="How a campaign's retained value split across coalition partners — grocery, fuel, hospitality, travel. The retailer never claims value a partner delivered."
        icon={<Network className="w-5 h-5" />}
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
              <h3 className="font-medium">Attributed value by partner</h3>
              <p className="text-sm text-[var(--muted)]">
                Multi-touch attribution across the partners each retained customer engaged with.
              </p>
            </div>
            {totalMargin > 0 ? (
              <div className="text-right">
                <div className="text-lg font-semibold tabular-nums">{aed(totalMargin.toFixed(2))} AED</div>
                <div className="text-xs text-[var(--muted)]">total attributed</div>
              </div>
            ) : null}
          </div>

          {rows.length === 0 ? (
            <EmptyState title="No coalition attribution yet"
              description="Register partners and record cross-partner activity, then attribute a campaign's retained value across them." />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHead>
                  <TableRow>
                    <Th>Partner</Th><Th>Type</Th><Th>Customers</Th>
                    <Th>Avg share</Th><Th>Attributed margin</Th>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={r.partner_name}>
                      <Td className="font-medium">{r.partner_name}</Td>
                      <Td><Badge variant={PARTNER_TONE[r.partner_type] ?? 'neutral'}>{r.partner_type}</Badge></Td>
                      <Td className="tabular-nums">{r.customers}</Td>
                      <Td className="w-40"><ShareBar weight={r.avg_weight} /></Td>
                      <Td className="tabular-nums font-medium">{aed(r.attributed_margin_aed)}</Td>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          <div className="mt-4 pt-4 border-t border-[var(--border)] text-xs text-[var(--muted)]">
            Coalition loyalty (SHARE, ADNOC, e&amp; Smiles) spans grocery, fuel, hospitality and
            travel. Attributing a retained customer&rsquo;s value across the partners they engaged
            with is how the number stays honest — the retailer&rsquo;s own campaign is one partner
            among them, and the weights sum to one.
          </div>
        </Card>
      </Reveal>
    </div>
  );
}
