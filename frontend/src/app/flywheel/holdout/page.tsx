'use client';

/**
 * Holdout — the control group as a first-class object.
 *
 * WHY THIS DESERVES ITS OWN SURFACE. The holdout is the only reason anyone
 * should believe this product works. Every incrementality number on the
 * neighbouring page is a subtraction against it. Leaving it as an
 * implementation detail buried in a campaign config wastes the single most
 * persuasive asset the programme has — and, worse, makes it easy for someone
 * under pressure to shrink the control group to "reach more customers" without
 * understanding they are destroying the ability to prove anything.
 *
 * THE DIAGNOSTIC THIS PAGE ADDS. Standardised mean difference between arms on
 * pre-treatment covariates. The stable-hash split should produce comparable
 * arms and usually does — but differential attrition, a mid-campaign audience
 * edit, or an eligibility filter applied to one arm all break comparability
 * silently, and every downstream number stays confidently wrong. Nothing in the
 * product detected that before this page existed.
 *
 * |SMD| > 0.10 is the conventional threshold for "these groups are not
 * comparable". It is shown per covariate rather than as a single pass/fail,
 * because WHICH covariate is unbalanced tells you what the confound is.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, Scale, Users } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TableBody, TableHead, TableRow, Td, Th,
} from '@/components/ui';
import { Reveal, SyntheticBadge } from '@/components/flywheel/motion';
import { fetchCampaignHoldout, fetchHoldoutOverview, pct } from '@/lib/flywheel';
import type { CampaignHoldout, HoldoutOverview } from '@/types/flywheel';

/** Human labels for the covariates. The raw column names are correct but
 *  unreadable to the marketer who most needs to understand this page. */
const COVARIATE_LABEL: Record<string, string> = {
  churn_probability: 'Churn risk at assignment',
  recency_days: 'Days since last purchase',
  frequency_90d: 'Purchases in last 90 days',
  monetary_90d_aed: 'Spend in last 90 days (AED)',
  avg_basket_aed: 'Average basket (AED)',
  tenure_days: 'Days since enrolment',
};

/** SMD rendered as a deviation from zero, with the ±0.10 threshold marked.
 *  Sign is kept visible: knowing WHICH arm is richer is what tells you the
 *  direction of the confound. */
function SmdBar({ smd, threshold }: { smd: number; threshold: number }) {
  const RANGE = 0.5;
  const clamped = Math.max(-RANGE, Math.min(RANGE, smd));
  const centre = 50;
  const width = (Math.abs(clamped) / RANGE) * 50;
  const left = clamped < 0 ? centre - width : centre;
  const balanced = Math.abs(smd) <= threshold;

  return (
    <div className="relative h-5 w-40 rounded bg-[var(--surface-2)] overflow-hidden">
      {/* acceptable band */}
      <div
        className="absolute inset-y-0 bg-[var(--success-soft)] opacity-40"
        style={{
          left: `${centre - (threshold / RANGE) * 50}%`,
          width: `${(threshold / RANGE) * 100}%`,
        }}
      />
      <div className="absolute inset-y-0 w-px bg-[var(--border-strong)]" style={{ left: '50%' }} />
      <div
        className={`absolute inset-y-1 rounded ${balanced ? 'bg-[var(--success)]' : 'bg-[var(--danger)]'}`}
        style={{ left: `${left}%`, width: `${Math.max(1.5, width)}%` }}
      />
    </div>
  );
}

export default function HoldoutPage() {
  const [overview, setOverview] = useState<HoldoutOverview | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<CampaignHoldout | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const o = await fetchHoldoutOverview();
      setOverview(o);
      if (o?.campaigns?.length && selected === null) setSelected(o.campaigns[0].campaign_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load holdout data');
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    (async () => {
      try {
        const d = await fetchCampaignHoldout(selected);
        if (!cancelled) setDetail(d);
      } catch {
        if (!cancelled) setDetail(null);
      }
    })();
    return () => { cancelled = true; };
  }, [selected]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-80" /></div>;
  }
  if (error && !overview) {
    return <div className="p-6"><ErrorState title="Holdout unavailable" description={error} onRetry={load} /></div>;
  }

  const campaigns = overview?.campaigns ?? [];
  const checks = detail?.balance?.checks ?? [];
  const summary = detail?.balance?.summary;

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel"
        title="Holdout"
        description="The customers deliberately left alone. Every incremental number in this product is a subtraction against them."
        icon={<Users className="w-5 h-5" />}
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
          <div className="flex items-start gap-3">
            <Scale className="w-5 h-5 mt-0.5 text-[var(--accent)] shrink-0" />
            <div>
              <h3 className="font-medium mb-1">Why some customers get nothing</h3>
              <p className="text-sm text-[var(--muted)] max-w-3xl">
                A held-out group receives no offer so their behaviour shows what would have
                happened anyway. Without it, &ldquo;4,000 contacted and 2,800 returned&rdquo; is
                unfalsifiable — most of them may have returned regardless, and the discount
                simply gave away margin on sales that were already coming. The holdout is
                what converts activity into evidence.
              </p>
            </div>
          </div>
        </Card>
      </Reveal>

      <div className="space-y-4">
        <Reveal>
          <Card padding="lg" className="mb-4">
            <h3 className="font-medium mb-3">Holdout across campaigns</h3>
            {campaigns.length === 0 ? (
              <EmptyState title="No campaigns" description="Nothing to hold out from yet." />
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <Th>Campaign</Th><Th>Status</Th><Th>Treatment</Th>
                      <Th>Control</Th><Th>Control share</Th><Th>Adequacy</Th>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {campaigns.map((c) => (
                      <TableRow
                        key={c.campaign_id}
                        onClick={() => setSelected(c.campaign_id)}
                        className={`cursor-pointer ${selected === c.campaign_id ? 'bg-[var(--surface-2)]' : ''}`}
                      >
                        <Td className="font-medium">{c.name}</Td>
                        <Td><Badge variant="neutral">{c.status}</Badge></Td>
                        <Td className="tabular-nums">{c.treatment_n}</Td>
                        <Td className="tabular-nums">{c.control_n}</Td>
                        <Td className="tabular-nums">{pct(c.control_share)}</Td>
                        <Td>
                          {c.adequate ? (
                            <Badge variant="success">adequate</Badge>
                          ) : (
                            <Badge variant="amber">directional only</Badge>
                          )}
                        </Td>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            <p className="text-xs text-[var(--muted)] mt-3">{overview?.note}</p>
          </Card>
        </Reveal>

        {/* ── BALANCE ────────────────────────────────────────────────────── */}
        {detail ? (
          <Reveal>
            <Card padding="lg">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div>
                  <h3 className="font-medium mb-1">Are the two groups comparable?</h3>
                  <p className="text-sm text-[var(--muted)] max-w-2xl">
                    Standardised mean difference on pre-treatment characteristics. If the
                    arms differ before the campaign started, any difference afterwards may
                    be the groups rather than the campaign.
                  </p>
                </div>
                {summary ? (
                  <Badge variant={summary.status === 'balanced' ? 'success'
                    : summary.status === 'imbalanced' ? 'danger' : 'neutral'}>
                    {summary.status === 'balanced' ? (
                      <><CheckCircle2 className="w-3 h-3 mr-1 inline" />comparable</>
                    ) : summary.status === 'imbalanced' ? (
                      <><AlertTriangle className="w-3 h-3 mr-1 inline" />not comparable</>
                    ) : 'unverified'}
                  </Badge>
                ) : null}
              </div>

              <div className="flex gap-6 mb-5 text-sm">
                <div>
                  <span className="text-[var(--muted)]">Treatment </span>
                  <span className="tabular-nums font-medium">{detail.arms.treatment}</span>
                </div>
                <div>
                  <span className="text-[var(--muted)]">Control </span>
                  <span className="tabular-nums font-medium">{detail.arms.control}</span>
                </div>
              </div>

              {checks.length === 0 ? (
                <EmptyState
                  title="Balance not verifiable"
                  description="This campaign has no audience with pre-treatment feature snapshots yet."
                />
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHead>
                      <TableRow>
                        <Th>Characteristic</Th><Th>Treatment</Th><Th>Control</Th>
                        <Th>SMD</Th><Th>Balance</Th>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {checks.map((c) => (
                        <TableRow key={c.covariate}>
                          <Td className="font-medium">
                            {COVARIATE_LABEL[c.covariate] ?? c.covariate}
                          </Td>
                          <Td className="tabular-nums">{c.treatment_mean.toFixed(2)}</Td>
                          <Td className="tabular-nums">{c.control_mean.toFixed(2)}</Td>
                          <Td className="tabular-nums">
                            <span className={c.is_balanced ? '' : 'text-[var(--danger)] font-medium'}>
                              {c.smd >= 0 ? '+' : ''}{c.smd.toFixed(3)}
                            </span>
                          </Td>
                          <Td><SmdBar smd={c.smd} threshold={c.threshold} /></Td>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}

              {summary && summary.status === 'imbalanced' ? (
                <div className="mt-4 flex items-start gap-2 text-sm text-[var(--danger)]">
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>{summary.note}</span>
                </div>
              ) : null}

              <div className="mt-5 pt-4 border-t border-[var(--border)] text-xs text-[var(--muted)]">
                {detail.assignment_method}
              </div>
            </Card>
          </Reveal>
        ) : null}
      </div>
    </div>
  );
}
