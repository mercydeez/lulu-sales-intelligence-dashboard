'use client';

/**
 * Flywheel — the command centre.
 *
 * The entry point to the retention loop: the signature ring, a one-glance
 * pipeline of campaigns by stage, and the setup path for a fresh install.
 *
 * DESIGN THESIS: spend the boldness on the loop ring (the brand's central
 * metaphor, doubling as a status indicator) and keep everything else quiet —
 * the existing operations-console palette, plain tables, no gratuitous glass.
 */
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Activity, ArrowRight, Database, Loader2, Play, Plus, Sparkles, Users,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton, StatCard,
} from '@/components/ui';
import {
  LoopRing, Reveal, Stagger, StaggerItem, SyntheticBadge, stageForStatus,
} from '@/components/flywheel/motion';
import {
  STATUS_TONE, aed, buildFeatures, fetchCampaigns, fetchHealth, scoreChurn,
  seedCustomers,
} from '@/lib/flywheel';
import type { CampaignSummary, FlywheelHealth } from '@/types/flywheel';

/** The pipeline columns — the loop's commercial stages, left to right. */
const PIPELINE: Array<{ label: string; statuses: string[] }> = [
  { label: 'Drafting', statuses: ['DRAFT', 'AUDIENCE_READY'] },
  { label: 'Simulated', statuses: ['SIMULATED'] },
  { label: 'In approval', statuses: [
    'PENDING_INVENTORY_REVIEW', 'PENDING_PROCUREMENT_REVIEW',
    'PENDING_FINANCE_APPROVAL', 'PENDING_MARKETING_APPROVAL'] },
  { label: 'Live', statuses: ['APPROVED', 'SCHEDULED', 'ACTIVE', 'PAUSED'] },
  { label: 'Measured', statuses: ['COMPLETED', 'MEASURED', 'CANCELLED'] },
];

export default function FlywheelCommandCentre() {
  const { user } = useAuth();
  const [health, setHealth] = useState<FlywheelHealth | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [setupStep, setSetupStep] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [h, c] = await Promise.all([fetchHealth(), fetchCampaigns()]);
      setHealth(h);
      setCampaigns(c.campaigns);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load Flywheel');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  /**
   * First-run setup. Deliberately sequential and narrated: each step depends on
   * the previous one (features need customers, scores need features), so
   * showing which step is running makes a slow seed legible rather than frozen.
   */
  const runSetup = useCallback(async () => {
    try {
      setSetupStep('Generating synthetic customers…');
      await seedCustomers({ customer_count: 600, history_days: 365 });
      setSetupStep('Building feature snapshots…');
      await buildFeatures();
      setSetupStep('Scoring churn risk…');
      await scoreChurn();
      setSetupStep(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Setup failed');
      setSetupStep(null);
    }
  }, [load]);

  // The ring shows the furthest-along campaign — the most interesting thing
  // happening right now, rather than an arbitrary first row.
  const leadCampaign = campaigns.find((c) => c.status === 'ACTIVE')
    ?? campaigns.find((c) => c.status.startsWith('PENDING'))
    ?? campaigns[0];

  const needsSetup = health !== null && health.customers === 0;

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-10 w-72" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (error && !health) {
    return <div className="p-6"><ErrorState title="Flywheel unavailable" description={error} onRetry={load} /></div>;
  }

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Retention & commercial orchestration"
        title="Flywheel"
        description="The retention loop that pays for itself — churn, uplift, stock, budget, approval, execution and true measured lift."
        icon={<Sparkles className="w-5 h-5" />}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <SyntheticBadge />
            <Link href="/flywheel/studio">
              <Button variant="primary"><Plus className="w-4 h-4 mr-1.5" />New campaign</Button>
            </Link>
          </div>
        }
      />

      {needsSetup ? (
        <Reveal>
          <Card padding="lg">
            <EmptyState
              icon={<Database className="w-6 h-6" />}
              title="Flywheel needs its customer layer"
              description={
                'The sales history has no customer identity, so Flywheel generates an honest '
                + 'synthetic layer with a fixed seed: 600 customers across ten behavioural '
                + 'archetypes, each purchase attributed to a real historical sale. Nothing '
                + 'in your existing sales data is modified.'
              }
              action={
                <Button variant="primary" onClick={runSetup} disabled={!!setupStep}>
                  {setupStep ? (
                    <><Loader2 className="w-4 h-4 mr-1.5 animate-spin" />{setupStep}</>
                  ) : (
                    <><Play className="w-4 h-4 mr-1.5" />Generate customers & score risk</>
                  )}
                </Button>
              }
            />
          </Card>
        </Reveal>
      ) : (
        <>
          <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-6">
            <StaggerItem>
              <StatCard label="Customers" value={health?.customers.toLocaleString() ?? '—'}
                        icon={<Users className="w-4 h-4" />} footnote="Synthetic, fixed seed" />
            </StaggerItem>
            <StaggerItem>
              <StatCard label="Campaigns" value={health?.campaigns ?? '—'}
                        icon={<Activity className="w-4 h-4" />}
                        footnote={`${campaigns.filter((c) => c.status === 'ACTIVE').length} live now`} />
            </StaggerItem>
            <StaggerItem>
              <StatCard label="Decisions recorded" value={health?.decisions.toLocaleString() ?? '—'}
                        footnote="Every one reproducible from its inputs" />
            </StaggerItem>
            <StaggerItem>
              <StatCard
                label="Redemptions" value={health?.redemptions.toLocaleString() ?? '—'}
                tone={health?.outbox_healthy === false ? 'amber' : undefined}
                footnote={health?.outbox_healthy === false
                  ? `${health.outbox_pending} events pending — live views may lag`
                  : 'Atomic & idempotent'}
              />
            </StaggerItem>
          </Stagger>

          <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
            {/* THE SIGNATURE MOMENT */}
            <Reveal>
              <Card padding="lg" className="h-full">
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  The loop
                </h2>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {leadCampaign
                    ? <>“{leadCampaign.name}” is at the highlighted stage.</>
                    : 'Create a campaign to start the loop.'}
                </p>
                <div className="mt-4 flex justify-center">
                  <LoopRing activeStage={stageForStatus(leadCampaign?.status)} size={240} />
                </div>
              </Card>
            </Reveal>

            <div className="space-y-6">
              <Reveal delay={0.05}>
                <Card padding="lg">
                  <div className="flex items-center justify-between gap-3 mb-4">
                    <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      Campaign pipeline
                    </h2>
                    <Link href="/flywheel/approvals"
                          className="text-xs font-medium text-teal-700 hover:underline dark:text-teal-300">
                      Approval inbox <ArrowRight className="inline w-3 h-3" />
                    </Link>
                  </div>

                  {campaigns.length === 0 ? (
                    <EmptyState
                      title="No campaigns yet"
                      description="Build one in the Campaign Studio — objective, audience, offers, stock, money, approval."
                      action={<Link href="/flywheel/studio"><Button variant="primary">Open Campaign Studio</Button></Link>}
                    />
                  ) : (
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                      {PIPELINE.map((column, ci) => {
                        const inColumn = campaigns.filter((c) => column.statuses.includes(c.status));
                        return (
                          <div key={column.label}>
                            <div className="mb-2 flex items-baseline justify-between">
                              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                                {column.label}
                              </span>
                              <span className="font-mono text-[11px] text-slate-400">{inColumn.length}</span>
                            </div>
                            <div className="space-y-2">
                              {inColumn.length === 0 && (
                                <div className="rounded-lg border border-dashed border-slate-200 p-3 text-center text-[11px] text-slate-400 dark:border-slate-700">
                                  none
                                </div>
                              )}
                              {inColumn.map((campaign, i) => (
                                <Reveal key={campaign.id} delay={ci * 0.04 + i * 0.03}>
                                  <Link href={`/flywheel/campaigns/${campaign.id}`} className="block group">
                                    <div className="rounded-lg border border-slate-200 p-3 transition-transform
                                                    duration-200 group-hover:-translate-y-0.5 group-hover:border-teal-300
                                                    focus-within:ring-2 focus-within:ring-teal-500
                                                    dark:border-slate-700 dark:group-hover:border-teal-600">
                                      <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                                        {campaign.name}
                                      </p>
                                      <div className="mt-2 flex items-center justify-between gap-2">
                                        <Badge variant={STATUS_TONE[campaign.status] ?? 'neutral'}>
                                          {campaign.status.replace(/_/g, ' ').toLowerCase()}
                                        </Badge>
                                        <span className="font-mono text-[11px] text-slate-400">
                                          {campaign.treatment_size.toLocaleString()}
                                        </span>
                                      </div>
                                      {campaign.pause_reason && (
                                        <p className="mt-2 line-clamp-2 text-[11px] text-rose-600 dark:text-rose-400">
                                          {campaign.pause_reason}
                                        </p>
                                      )}
                                    </div>
                                  </Link>
                                </Reveal>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </Card>
              </Reveal>

              <Reveal delay={0.1}>
                <div className="grid gap-4 sm:grid-cols-3">
                  <Link href="/flywheel/customers" className="group">
                    <Card padding="md" hover="lift" className="h-full">
                      <Users className="w-5 h-5 text-teal-700 dark:text-teal-300" />
                      <p className="mt-2 text-sm font-medium text-slate-900 dark:text-slate-100">
                        Customers at risk
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        Churn scores with the drivers behind each one.
                      </p>
                    </Card>
                  </Link>
                  <Link href="/flywheel/budget" className="group">
                    <Card padding="md" hover="lift" className="h-full">
                      <span aria-hidden className="block text-teal-700 dark:text-teal-300 font-mono text-lg">AED</span>
                      <p className="mt-2 text-sm font-medium text-slate-900 dark:text-slate-100">
                        Budget & exposure
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        Allocated, reserved, committed, spent — with the full ledger.
                      </p>
                    </Card>
                  </Link>
                  <Link href="/flywheel/models" className="group">
                    <Card padding="md" hover="lift" className="h-full">
                      <Sparkles className="w-5 h-5 text-teal-700 dark:text-teal-300" />
                      <p className="mt-2 text-sm font-medium text-slate-900 dark:text-slate-100">
                        Models & honesty
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        Which model is live, its metrics, and what it cannot claim.
                      </p>
                    </Card>
                  </Link>
                </div>
              </Reveal>
            </div>
          </div>
        </>
      )}

      <p className="mt-8 text-xs text-slate-400 dark:text-slate-500 max-w-3xl">
        Models propose; only deterministic, policy-checked services touch money or stock.
        All customers, treatment histories and campaign outcomes are synthetic —
        no production accuracy is claimed.
      </p>
    </div>
  );
}
