'use client';

/**
 * Shadow mode — what the models would have done, and whether they earned trust.
 *
 * THE RULING THIS SURFACES (20 Jul 2026). The deterministic rule tier is the
 * production decision path. Models score continuously in shadow, their
 * disagreements with the shipping path are counted, and they are promoted only
 * when a pre-registered holdout shows them beating rules with a confidence
 * interval excluding zero.
 *
 * WHY THAT IS A CREDENTIAL AND NOT AN APOLOGY. Three training runs produced
 * three different winners and Qini swung from +1.13 to -3.80 — at n=300 with
 * ~16 positives in the test split, none of it is distinguishable from noise.
 * A product that shipped whichever model won the last run would be shipping a
 * coin flip. Showing the bar, the standing against it, and the reason nothing
 * has cleared it is what a technical buyer's due diligence is actually looking
 * for.
 *
 * THE TRAP THIS PAGE MUST NOT FALL INTO. When no trained model is registered,
 * the comparison is the rule tier against itself and the disagreement rate is
 * 0% BY CONSTRUCTION. Rendered plainly that reads as "the model agrees with
 * policy perfectly" — the most flattering possible reading of a measurement
 * that measured nothing. The backend flags it and this page states it loudly.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Ban, GitCompare, Lock, RefreshCw } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TableBody, TableHead, TableRow, Td, Th,
} from '@/components/ui';
import { Reveal, Stagger, StaggerItem, SyntheticBadge } from '@/components/flywheel/motion';
import { aed, fetchShadow, pct, runShadowScore } from '@/lib/flywheel';
import type { ShadowOverview } from '@/types/flywheel';

const KIND_LABEL: Record<string, string> = {
  action: 'Different decision',
  magnitude: 'Different size',
  both: 'Different decision and size',
};

export default function ShadowModePage() {
  const [data, setData] = useState<ShadowOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try { setData(await fetchShadow()); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load shadow mode'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const rescore = async () => {
    setBusy(true);
    try { await runShadowScore(); setData(await fetchShadow()); }
    catch (e) { setError(e instanceof Error ? e.message : 'Scoring pass failed'); }
    finally { setBusy(false); }
  };

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-80" /></div>;
  }
  if (error && !data) {
    return <div className="p-6"><ErrorState title="Shadow mode unavailable" description={error} onRetry={load} /></div>;
  }

  const comparison = data?.comparison ?? [];
  const promotion = data?.promotion ?? [];

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel"
        title="Shadow mode"
        description="Models propose. Rules decide. Promotion is earned against a bar fixed in advance, not granted because a metric looked good."
        icon={<GitCompare className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <SyntheticBadge />
            <Button variant="ghost" size="sm" onClick={rescore} disabled={busy}>
              {busy ? 'Scoring…' : 'Run scoring pass'}
            </Button>
            <Button variant="ghost" onClick={load} aria-label="Refresh">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        }
      />

      <Reveal>
        <Card padding="lg" className="mb-6">
          <div className="flex items-start gap-3">
            <Lock className="w-5 h-5 mt-0.5 text-teal-700 shrink-0" />
            <div>
              <h3 className="font-medium mb-1">The governing rule</h3>
              <p className="text-sm text-ink-muted max-w-3xl">{data?.governing_rule}</p>
            </div>
          </div>
        </Card>
      </Reveal>

      <Stagger>
        <StaggerItem>
          <Card padding="lg" className="mb-4">
            <h3 className="font-medium mb-3">Agreement with the shipping path</h3>
            {comparison.length === 0 ? (
              <EmptyState
                title="No shadow decisions recorded"
                description="Run a scoring pass to compare every model against the rule tier."
              />
            ) : (
              <div className="space-y-4">
                {comparison.map((c) => (
                  <div key={c.model_label}
                    className="rounded-lg border border-line p-4">
                    <div className="flex flex-wrap items-start justify-between gap-4 mb-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{c.model_label}</span>
                          {c.is_self_comparison ? (
                            <Badge variant="danger">
                              <AlertTriangle className="w-3 h-3 me-1 inline" />
                              not a real comparison
                            </Badge>
                          ) : (
                            <Badge variant="neutral">{c.scored} scored</Badge>
                          )}
                        </div>
                      </div>
                      <div className="text-end">
                        <div className="text-2xl font-semibold tabular-nums">
                          {pct(c.disagreement_rate)}
                        </div>
                        <div className="text-xs text-ink-muted">disagreement rate</div>
                      </div>
                    </div>

                    {/* THE GUARD. A 0% rate from a self-comparison must never be
                        allowed to read as agreement. */}
                    {c.is_self_comparison && c.self_comparison_warning ? (
                      <div className="flex items-start gap-2 text-sm text-rose-600 bg-rose-50 rounded p-3 mb-3">
                        <Ban className="w-4 h-4 mt-0.5 shrink-0" />
                        <span>{c.self_comparison_warning}</span>
                      </div>
                    ) : (
                      <>
                        <div className="flex flex-wrap gap-2 mb-3">
                          {Object.entries(c.by_kind).map(([kind, count]) => (
                            <Badge key={kind} variant={kind === 'magnitude' ? 'neutral' : 'amber'}>
                              {KIND_LABEL[kind] ?? kind}: {count}
                            </Badge>
                          ))}
                        </div>
                        <div className="text-sm">
                          <span className="text-ink-muted">Model claims </span>
                          <span className="tabular-nums font-medium">
                            {aed(c.claimed_eiv_delta_aed)} AED
                          </span>
                          <span className="text-ink-muted"> more EIV than rules</span>
                        </div>
                        <p className="text-xs text-ink-muted mt-2">{c.claimed_delta_note}</p>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </StaggerItem>

        <StaggerItem>
          <Card padding="lg">
            <h3 className="font-medium mb-1">Standing against the promotion bar</h3>
            <p className="text-sm text-ink-muted mb-4">
              The bar was fixed before any evidence was gathered. It is not adjustable from
              this screen, by design.
            </p>
            {promotion.length === 0 ? (
              <EmptyState title="No models registered" description="Nothing is in shadow yet." />
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <Th>Model</Th><Th>Status</Th><Th>Qualifying readouts</Th>
                      <Th>Disagreement</Th><Th>Eligible</Th><Th>Blocked by</Th>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {promotion.map((p) => (
                      <TableRow key={p.model_label}>
                        <Td className="font-medium">{p.model_label}</Td>
                        <Td><Badge variant={p.status === 'promoted' ? 'success' : 'neutral'}>
                          {p.status}
                        </Badge></Td>
                        <Td className="tabular-nums">
                          {p.readouts_passed}/{p.readouts_required}
                        </Td>
                        <Td className="tabular-nums">
                          {p.disagreement_rate === null ? '—' : pct(p.disagreement_rate)}
                          <span className="text-ink-muted"> / {pct(p.max_disagreement_rate, 0)} max</span>
                        </Td>
                        <Td>
                          {p.eligible_for_promotion
                            ? <Badge variant="success">eligible</Badge>
                            : <Badge variant="neutral">not yet</Badge>}
                        </Td>
                        <Td>
                          <ul className="text-xs text-ink-muted space-y-1">
                            {p.blockers.map((b, i) => <li key={i}>• {b}</li>)}
                          </ul>
                        </Td>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </Card>
        </StaggerItem>
      </Stagger>
    </div>
  );
}
