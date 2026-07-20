'use client';

/**
 * Approval Inbox (§20.3).
 *
 * Shows the whole queue to everyone in scope — transparency about what is
 * waiting matters more than hiding rows someone cannot action. Steps the viewer
 * cannot decide render with the reason instead of a disabled button.
 */
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
} from '@/components/ui';
import { ApprovalChain, Reveal, SyntheticBadge } from '@/components/flywheel/motion';
import { aed, decideApproval, fetchApproval, fetchApprovals } from '@/lib/flywheel';
import type { ApprovalRequestDetail, ApprovalRequestSummary } from '@/types/flywheel';

export default function ApprovalInbox() {
  const [requests, setRequests] = useState<ApprovalRequestSummary[]>([]);
  const [selected, setSelected] = useState<ApprovalRequestDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'pending' | 'all'>('pending');

  const load = useCallback(async (status: string) => {
    setError(null);
    try {
      const result = await fetchApprovals(status);
      setRequests(result.requests);
      // Keep the open detail in sync after a decision, rather than leaving a
      // stale panel showing a step that has since been approved.
      if (result.requests.length && !selected) {
        setSelected(await fetchApproval(result.requests[0].request_id));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load approvals');
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => { void load(filter); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [filter]);

  const open = useCallback(async (id: number) => {
    setError(null);
    try { setSelected(await fetchApproval(id)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not open request'); }
  }, []);

  const decide = useCallback(async (stepId: number, decision: string) => {
    if (!selected) return;
    setBusy(true); setError(null);
    try {
      await decideApproval(stepId, decision);
      // Refresh both panes — a decision can change the request's status and
      // remove it from the pending list entirely.
      const [detail, list] = await Promise.all([
        fetchApproval(selected.request_id), fetchApprovals(filter),
      ]);
      setSelected(detail);
      setRequests(list.requests);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not record the decision');
    } finally {
      setBusy(false);
    }
  }, [selected, filter]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-96" /></div>;
  }

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel"
        title="Approval inbox"
        description="Campaigns and requisitions waiting on a decision. No offer is issued and no budget reserved until every step is approved."
        icon={<Inbox className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <SyntheticBadge />
            <Button variant="ghost" onClick={() => load(filter)} aria-label="Refresh">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        }
      />

      <div className="mb-4 flex gap-2">
        {(['pending', 'all'] as const).map((f) => (
          <button
            key={f} type="button" onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline
                        focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 ${
              filter === f ? 'bg-teal-700 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300'
            }`}
            aria-pressed={filter === f}
          >
            {f === 'pending' ? 'Awaiting decision' : 'All requests'}
          </button>
        ))}
      </div>

      {error && (
        <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /><span>{error}</span>
        </div>
      )}

      {requests.length === 0 ? (
        <Card padding="lg">
          <EmptyState
            icon={<Inbox className="w-6 h-6" />}
            title={filter === 'pending' ? 'Nothing awaiting approval' : 'No approval requests yet'}
            description="Submit a campaign from the Campaign Studio to open an approval chain."
            action={<Link href="/flywheel/studio"><Button variant="primary">Open Campaign Studio</Button></Link>}
          />
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
          <div className="space-y-2">
            {requests.map((request, i) => (
              <Reveal key={request.request_id} delay={i * 0.03}>
                <button
                  type="button"
                  onClick={() => open(request.request_id)}
                  aria-current={selected?.request_id === request.request_id ? 'true' : undefined}
                  className={`w-full rounded-lg border p-4 text-left transition-colors
                              focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2
                              focus-visible:outline-teal-600 ${
                    selected?.request_id === request.request_id
                      ? 'border-teal-400 bg-teal-50/50 dark:border-teal-600 dark:bg-teal-500/5'
                      : 'border-slate-200 hover:border-slate-300 dark:border-slate-700'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                      {request.campaign_name ?? `Request #${request.request_id}`}
                    </p>
                    <Badge variant={
                      request.status === 'approved' ? 'success'
                        : request.status === 'rejected' ? 'danger'
                          : request.status === 'pending' ? 'amber' : 'neutral'
                    }>
                      {request.status}
                    </Badge>
                  </div>
                  <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
                    <div className="flex gap-1">
                      <dt>Discount</dt>
                      <dd className="font-mono text-slate-700 dark:text-slate-300">
                        {aed(request.discount_exposure_aed, { compact: true })}
                      </dd>
                    </div>
                    {request.expected_roi !== null && (
                      <div className="flex gap-1">
                        <dt>ROI</dt>
                        <dd className="font-mono text-teal-700 dark:text-teal-300">
                          {request.expected_roi.toFixed(2)}×
                        </dd>
                      </div>
                    )}
                  </dl>
                  {request.awaiting.length > 0 && (
                    <p className="mt-2 text-[11px] text-slate-500">
                      Awaiting: {request.awaiting.join(', ')}
                      {request.can_act && (
                        <span className="ml-1.5 font-medium text-teal-700 dark:text-teal-300">
                          — you can act
                        </span>
                      )}
                    </p>
                  )}
                </button>
              </Reveal>
            ))}
          </div>

          {selected && (
            <Card padding="lg">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                    {selected.campaign_name ?? `Request #${selected.request_id}`}
                  </h2>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {selected.request_type.replace(/_/g, ' ')} · requested by{' '}
                    {selected.requested_by ?? 'unknown'}
                    {selected.expires_at && ` · expires ${new Date(selected.expires_at).toLocaleDateString()}`}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-2xl text-slate-900 dark:text-slate-100">
                    {selected.progress.approved}/{selected.progress.total}
                  </p>
                  <p className="text-[11px] text-slate-500">steps approved</p>
                </div>
              </div>

              <dl className="mt-5 grid gap-4 sm:grid-cols-3 rounded-lg bg-slate-50 p-4 dark:bg-slate-800/50">
                <div>
                  <dt className="text-[11px] text-slate-500">Discount exposure</dt>
                  <dd className="font-mono text-lg text-amber-700 dark:text-amber-400">
                    {aed(selected.discount_exposure_aed)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-slate-500">Procurement exposure</dt>
                  <dd className="font-mono text-lg text-amber-700 dark:text-amber-400">
                    {aed(selected.procurement_exposure_aed)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-slate-500">Expected ROI</dt>
                  <dd className="font-mono text-lg text-teal-700 dark:text-teal-300">
                    {selected.expected_roi !== null ? `${selected.expected_roi.toFixed(2)}×` : '—'}
                  </dd>
                </div>
              </dl>

              <h3 className="mt-6 mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                Approval chain
              </h3>
              <ApprovalChain steps={selected.steps} onDecide={decide} busy={busy} />

              {selected.campaign_id && (
                <div className="mt-6">
                  <Link href={`/flywheel/campaigns/${selected.campaign_id}`}
                        className="text-xs font-medium text-teal-700 hover:underline dark:text-teal-300">
                    View the full campaign →
                  </Link>
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
