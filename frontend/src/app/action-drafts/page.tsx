'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import {
  PageHeader, Card, Badge, Button, Modal, EmptyState, SkeletonCard, ErrorState, useToast,
} from '@/components/ui';
import type { BadgeVariant } from '@/components/ui';
import { apiGet, apiPost, ApiError } from '@/lib/apiClient';
import { Wand2, CheckCircle2, XCircle } from 'lucide-react';

const STATUS_TONE: Record<string, BadgeVariant> = {
  draft: 'amber', approved: 'success', rejected: 'neutral',
};
const TYPE_LABEL: Record<string, string> = {
  supplier_email: 'Supplier email', markdown_proposal: 'Markdown proposal',
  promotion_proposal: 'Promotion', review_task: 'Review task', purchase_order: 'Purchase order',
};

interface DraftRow { id: number; draft_type: string; status: string; title: string;
  summary: string | null; source_action_type: string | null; created_by: string | null;
  reviewed_by: string | null; created_at: string | null; }
interface DraftDetail extends DraftRow { payload: Record<string, unknown>; review_note?: string | null; }

const FILTERS = [
  { label: 'To review', value: 'draft' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
  { label: 'All', value: '' },
];

export default function ActionDraftsPage() {
  const { user } = useAuth();
  const { show } = useToast();
  const isOperator = ['super_admin', 'admin', 'regional_manager', 'store_manager'].includes(user?.role ?? '')
    || !!user?.permissions?.can_manage_inventory;

  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('draft');
  const [detail, setDetail] = useState<DraftDetail | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const qs = filter ? `?status=${filter}` : '';
      setDrafts((await apiGet<{ drafts: DraftRow[] }>(`/api/action-drafts${qs}`)).drafts ?? []);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load drafts');
    } finally { setLoading(false); }
  }, [filter]);

  useEffect(() => { if (isOperator) load(); else setLoading(false); }, [isOperator, load]);

  const open = async (id: number) => {
    try { setDetail(await apiGet<DraftDetail>(`/api/action-drafts/${id}`)); }
    catch (e) { show(e instanceof ApiError ? e.message : "Couldn't open the draft", { variant: 'error' }); }
  };

  // Approve/reject are terminal (the backend refuses re-review), so both are
  // two-step: first click arms the button, second click within 3s executes.
  const [arming, setArming] = useState<'approve' | 'reject' | null>(null);
  const disarmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const disarm = useCallback(() => {
    if (disarmTimer.current) { clearTimeout(disarmTimer.current); disarmTimer.current = null; }
    setArming(null);
  }, []);
  useEffect(() => () => { if (disarmTimer.current) clearTimeout(disarmTimer.current); }, []);

  const review = async (decision: 'approve' | 'reject') => {
    if (!detail) return;
    if (arming !== decision) {
      // First click (or switching sides): arm and auto-disarm after 3s.
      if (disarmTimer.current) clearTimeout(disarmTimer.current);
      setArming(decision);
      disarmTimer.current = setTimeout(() => setArming(null), 3000);
      return;
    }
    disarm();
    setBusy(true);
    try {
      await apiPost(`/api/action-drafts/${detail.id}/${decision}`, {});
      show(decision === 'approve'
        ? 'Approved — your decision is recorded. Nothing is sent or executed automatically.'
        : 'Rejected — Sage will keep the underlying finding until it recurs or resolves.',
        { variant: decision === 'approve' ? 'success' : 'info' });
      setDetail(null);
      await load();
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Action failed', { variant: 'error' });
    } finally { setBusy(false); }
  };

  if (!isOperator) {
    return (
      <main className="min-h-screen p-4 md:p-8"><div className="max-w-3xl mx-auto">
        <Card padding="lg" className="text-center">
          <Wand2 className="w-8 h-8 text-amber-500 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-ink">Operator access required</h2>
        </Card>
      </div></main>
    );
  }

  const renderPayload = (d: DraftDetail) => {
    const p = d.payload || {};
    if (d.draft_type === 'supplier_email') {
      return (
        <div className="space-y-2 text-sm">
          <div><span className="text-ink-muted text-xs">To</span><p className="text-ink">{String(p.to ?? '')}</p></div>
          <div><span className="text-ink-muted text-xs">Subject</span><p className="text-ink font-medium">{String(p.subject ?? '')}</p></div>
          <div><span className="text-ink-muted text-xs">Body</span><p className="text-ink whitespace-pre-wrap rounded-xl bg-surface-2/60 p-3">{String(p.body ?? '')}</p></div>
        </div>
      );
    }
    const steps = (p.proposed_steps || p.next_steps) as string[] | undefined;
    return (
      <div className="space-y-2 text-sm">
        {p.rationale != null && <div><span className="text-ink-muted text-xs">Rationale</span><p className="text-ink">{String(p.rationale)}</p></div>}
        {p.proposed_promo != null && <div><span className="text-ink-muted text-xs">Proposed</span><p className="text-ink">{String(p.proposed_promo)}</p></div>}
        {p.task != null && <div><span className="text-ink-muted text-xs">Task</span><p className="text-ink">{String(p.task)}</p></div>}
        {p.recommended_action != null && <div><span className="text-ink-muted text-xs">Recommended</span><p className="text-ink">{String(p.recommended_action)}</p></div>}
        {Array.isArray(steps) && (
          <div><span className="text-ink-muted text-xs">Steps</span>
            <ul className="list-disc ms-5 text-ink">{steps.map((s, i) => <li key={i}>{s}</li>)}</ul>
          </div>
        )}
      </div>
    );
  };

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        <PageHeader
          title="Action drafts"
          description="System-drafted next actions from diagnostics findings. You approve; nothing is sent or executed automatically."
          icon={<Wand2 className="w-5 h-5" />}
        />

        <div className="flex flex-wrap gap-2 mb-6">
          {FILTERS.map((f) => (
            <button key={f.value} onClick={() => setFilter(f.value)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                filter === f.value ? 'bg-teal-600 text-white' : 'text-ink-muted hover:bg-surface-2 border border-line'}`}>
              {f.label}
            </button>
          ))}
        </div>

        {loading ? <div className="space-y-3"><SkeletonCard /><SkeletonCard /></div>
        : error ? <ErrorState title="Couldn't load drafts" description={error} onRetry={load} />
        : drafts.length === 0 ? <EmptyState title="No drafts" description="Draft an action from a finding on the Insights page." />
        : (
          <div className="space-y-2">
            {drafts.map((d) => (
              <button key={d.id} onClick={() => open(d.id)}
                className="w-full flex items-center justify-between gap-3 rounded-xl border border-line p-4 hover:bg-surface-2/60 text-start transition-all">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink truncate">{d.title}</p>
                  <p className="text-xs text-ink-muted">{TYPE_LABEL[d.draft_type] ?? d.draft_type} · {d.summary}</p>
                </div>
                <Badge variant={STATUS_TONE[d.status] ?? 'neutral'}>{d.status}</Badge>
              </button>
            ))}
          </div>
        )}

        <Modal open={!!detail} onClose={() => { setDetail(null); disarm(); }} title={detail?.title ?? 'Draft'}>
          {detail && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Badge variant="neutral">{TYPE_LABEL[detail.draft_type] ?? detail.draft_type}</Badge>
                <Badge variant={STATUS_TONE[detail.status] ?? 'neutral'}>{detail.status}</Badge>
              </div>
              {renderPayload(detail)}
              <p className="text-xs text-ink-muted">
                Autonomy level 1 — approving records your decision. The system never sends the email,
                places the order, or changes prices. Execution stays with you.
              </p>
              {detail.status === 'draft' && (
                <div>
                  <div className="flex items-center gap-2">
                    <Button onClick={() => review('approve')} disabled={busy} loading={busy && arming === null}>
                      <CheckCircle2 className="w-4 h-4 me-1.5" />
                      {arming === 'approve' ? 'Confirm approval' : 'Approve'}
                    </Button>
                    <Button variant={arming === 'reject' ? 'danger' : 'secondary'}
                      onClick={() => review('reject')} disabled={busy}>
                      <XCircle className="w-4 h-4 me-1.5" />
                      {arming === 'reject' ? 'Confirm reject' : 'Reject'}
                    </Button>
                  </div>
                  {arming && (
                    <p className="mt-2 text-xs text-ink-muted" role="status">
                      {arming === 'approve'
                        ? 'Click again to confirm. Approval records your decision — nothing is sent or executed automatically.'
                        : 'Click again to confirm. A rejected draft can’t be reopened — Sage can draft a fresh one from the finding.'}
                    </p>
                  )}
                </div>
              )}
              {detail.reviewed_by && (
                <p className="text-xs text-ink-muted">Reviewed by {detail.reviewed_by}.</p>
              )}
            </div>
          )}
        </Modal>
      </div>
    </main>
  );
}
