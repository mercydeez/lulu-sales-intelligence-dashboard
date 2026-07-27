'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Building2, ArrowLeft, History, StickyNote } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import {
  PageHeader, Button, Card, Badge, Select, Input, EmptyState,
  SkeletonCard, useToast, Stagger, RevealItem, NoPermissionState,
} from '@/components/ui';
import type { BadgeVariant } from '@/components/ui';

// Keep in sync with services/tenant_lifecycle.STATES + migration 042 CHECK.
const STATUSES = [
  'trial', 'onboarding', 'active', 'payment_pending', 'past_due',
  'suspended', 'cancelled', 'deletion_requested', 'deleted',
] as const;

const STATUS_TONE: Record<string, BadgeVariant> = {
  trial: 'violet', onboarding: 'violet', active: 'success',
  payment_pending: 'amber', past_due: 'amber',
  suspended: 'danger', cancelled: 'neutral',
  deletion_requested: 'warning', deleted: 'neutral',
};

interface Tenant { id: number; slug: string; name: string; plan: string; status: string; user_count: number; }
interface StatusEvent { from_status: string; to_status: string; reason: string | null; changed_email: string | null; created_at: string | null; }
interface Note { id: number; note: string; author_email: string | null; created_at: string | null; }

export default function TenantConsolePage() {
  const { user, authFetch } = useAuth();
  const { t } = useLanguage();
  const { show } = useToast();
  // Platform Console boundary: the backend gates these endpoints on the
  // is_platform_developer flag, NOT on role — every self-signup owner is a
  // super_admin, so a role gate here would show customers an empty console.
  const isPlatformDev = Boolean(user?.is_platform_developer);

  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [metrics, setMetrics] = useState<{ tenants_active: number; estimated_mrr_aed: number;
    total_users: number; enterprise_active: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Tenant | null>(null);
  const [events, setEvents] = useState<StatusEvent[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [targetStatus, setTargetStatus] = useState('');
  const [reason, setReason] = useState('');
  const [newNote, setNewNote] = useState('');
  const [busy, setBusy] = useState(false);

  const loadTenants = useCallback(async () => {
    setLoading(true);
    try {
      const [res, m] = await Promise.all([authFetch('/api/tenants'), authFetch('/api/tenants/metrics')]);
      if (res.ok) setTenants((await res.json()).tenants ?? []);
      if (m.ok) setMetrics(await m.json());
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  const loadDetail = useCallback(async (t: Tenant) => {
    setSelected(t);
    setTargetStatus('');
    setReason('');
    const [evRes, noteRes] = await Promise.all([
      authFetch(`/api/tenants/${t.id}/status-events`),
      authFetch(`/api/tenants/${t.id}/notes`),
    ]);
    setEvents(evRes.ok ? (await evRes.json()).events ?? [] : []);
    setNotes(noteRes.ok ? (await noteRes.json()).notes ?? [] : []);
  }, [authFetch]);

  useEffect(() => { if (isPlatformDev) loadTenants(); else setLoading(false); }, [isPlatformDev, loadTenants]);

  const applyStatus = async () => {
    if (!selected || !targetStatus) return;
    setBusy(true);
    try {
      const res = await authFetch(`/api/tenants/${selected.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: targetStatus, reason: reason || null }),
      });
      if (res.ok) {
        show(`Tenant set to ${targetStatus}`, { variant: 'success' });
        await loadTenants();
        await loadDetail({ ...selected, status: targetStatus });
      } else {
        const err = await res.json().catch(() => ({}));
        show(err.detail || 'Transition rejected', { variant: 'error' });
      }
    } finally {
      setBusy(false);
    }
  };

  const addNote = async () => {
    if (!selected || !newNote.trim()) return;
    setBusy(true);
    try {
      const res = await authFetch(`/api/tenants/${selected.id}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: newNote.trim() }),
      });
      if (res.ok) { setNewNote(''); await loadDetail(selected); }
      else show('Could not add note', { variant: 'error' });
    } finally {
      setBusy(false);
    }
  };

  if (!isPlatformDev) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-3xl mx-auto">
          <Card padding="none">
            <NoPermissionState
              title="Platform developer access required"
              description="Tenant management is limited to platform developers."
            />
          </Card>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title={t('tenants.console.title')}
          description={t('tenants.console.description')}
          icon={<Building2 className="w-5 h-5" />}
          actions={
            <Link href="/admin">
              <Button variant="secondary" size="md"><ArrowLeft className="w-4 h-4" />Admin</Button>
            </Link>
          }
        />

        {metrics && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            <Card padding="lg"><p className="text-xs text-ink-muted">Active tenants</p><p className="text-2xl font-semibold text-ink mt-0.5">{metrics.tenants_active}</p></Card>
            <Card padding="lg"><p className="text-xs text-ink-muted">Est. MRR</p><p className="text-2xl font-semibold text-ink mt-0.5">AED {metrics.estimated_mrr_aed.toLocaleString('en-AE', { maximumFractionDigits: 0 })}</p></Card>
            <Card padding="lg"><p className="text-xs text-ink-muted">Total users</p><p className="text-2xl font-semibold text-ink mt-0.5">{metrics.total_users}</p></Card>
            <Card padding="lg"><p className="text-xs text-ink-muted">Enterprise</p><p className="text-2xl font-semibold text-ink mt-0.5">{metrics.enterprise_active}</p></Card>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Tenant list */}
          <div className="lg:col-span-2 space-y-3">
            {loading ? <SkeletonCard /> : tenants.length === 0 ? (
              <EmptyState title="No tenants" description="No tenants found." />
            ) : (
              <Stagger className="space-y-2">
                {tenants.map((t) => (
                  <RevealItem key={t.id}>
                    <button onClick={() => loadDetail(t)}
                      className={`w-full text-start rounded-xl border p-4 transition-all ${
                        selected?.id === t.id ? 'border-teal-400 bg-teal-50' : 'border-line hover:bg-surface-2/60'}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-ink truncate">{t.name}</span>
                        <Badge variant={STATUS_TONE[t.status] ?? 'neutral'}>{t.status}</Badge>
                      </div>
                      <p className="text-xs text-ink-muted mt-1">
                        {t.slug} · {t.plan} · {t.user_count} user{t.user_count === 1 ? '' : 's'}
                      </p>
                    </button>
                  </RevealItem>
                ))}
              </Stagger>
            )}
          </div>

          {/* Detail */}
          <div className="lg:col-span-3">
            {!selected ? (
              <EmptyState title="Select a tenant" description="Pick a tenant to manage its lifecycle." />
            ) : (
              <div className="space-y-6">
                <Card padding="lg">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Lifecycle</h3>
                    <Badge variant={STATUS_TONE[selected.status] ?? 'neutral'}>{selected.status}</Badge>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
                    <Select label="New status" value={targetStatus} onChange={(e) => setTargetStatus(e.target.value)}>
                      <option value="">—</option>
                      {STATUSES.filter((s) => s !== selected.status).map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </Select>
                    <Input label="Reason (audited)" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. non-payment" />
                  </div>
                  <div className="mt-4">
                    <Button onClick={applyStatus} disabled={!targetStatus || busy}>Apply transition</Button>
                  </div>
                </Card>

                <Card padding="lg">
                  <div className="flex items-center gap-2 mb-3">
                    <History className="w-4 h-4 text-teal-600" />
                    <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Transition history</h3>
                  </div>
                  {events.length === 0 ? <p className="text-sm text-ink-muted">No transitions recorded.</p> : (
                    <ul className="space-y-2">
                      {events.map((e, i) => (
                        <li key={i} className="text-sm text-ink-soft border-b border-line/60 pb-2 last:border-0">
                          <span className="font-medium">{e.from_status ?? '—'} → {e.to_status}</span>
                          {e.reason && <span className="text-ink-muted"> · {e.reason}</span>}
                          <span className="block text-xs text-ink-muted">
                            {e.changed_email ?? 'system'} · {e.created_at ? new Date(e.created_at).toLocaleString() : ''}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>

                <Card padding="lg">
                  <div className="flex items-center gap-2 mb-3">
                    <StickyNote className="w-4 h-4 text-teal-600" />
                    <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Support notes</h3>
                  </div>
                  <div className="flex gap-2 mb-4">
                    <Input value={newNote} onChange={(e) => setNewNote(e.target.value)} placeholder="Add a note…" className="flex-1" />
                    <Button variant="secondary" onClick={addNote} disabled={!newNote.trim() || busy}>Add</Button>
                  </div>
                  {notes.length === 0 ? <p className="text-sm text-ink-muted">No notes yet.</p> : (
                    <ul className="space-y-2">
                      {notes.map((n) => (
                        <li key={n.id} className="text-sm text-ink-soft border-b border-line/60 pb-2 last:border-0">
                          {n.note}
                          <span className="block text-xs text-ink-muted">
                            {n.author_email ?? 'operator'} · {n.created_at ? new Date(n.created_at).toLocaleString() : ''}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
