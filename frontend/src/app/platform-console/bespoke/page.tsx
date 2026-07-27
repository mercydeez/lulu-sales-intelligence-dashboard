'use client';

/**
 * Platform Console — Bespoke Atelier (internal, platform developers only).
 *
 * The "Rolls-Royce" ledger: what clients asked for that the product doesn't do
 * yet, tracked from request through delivery, alongside the Atelier advisor that
 * turns a plain-language client need into catalog settings + bespoke drafts.
 *
 * Gated on `user.is_platform_developer` — NOT super_admin (tenant owners are
 * super_admins too). The subnav is replicated inline (no shared component) so
 * the three console pages stay merge-conflict-free.
 */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import {
  PageHeader, Card, Select, Input, Button, Badge, Table, TableHead, TableBody,
  TableRow, Th, Td, Modal, EmptyState, SkeletonCard, NoPermissionState, useToast,
} from '@/components/ui';
import type { BadgeVariant } from '@/components/ui';
import AtelierChat from '@/components/platform-console/AtelierChat';

// ── Contract (backend: /api/admin/dev/bespoke) ─────────────────────────────

type BespokeStatus = 'requested' | 'scoped' | 'approved' | 'building' | 'delivered' | 'declined';
type Priority = 'low' | 'medium' | 'high' | 'vip';

interface BespokeRequest {
  id: number;
  tenant_id: number | null;
  title: string;
  client_description: string;
  status: BespokeStatus;
  priority: Priority;
  scoping_notes: string | null;
  estimate: string | null;
  delivered_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}
interface Tenant { id: number; name: string; plan: string }

// The status machine (mirrors services/bespoke.TRANSITIONS). The UI only offers
// legal next moves; the backend re-checks, so this is convenience not trust.
const TRANSITIONS: Record<BespokeStatus, BespokeStatus[]> = {
  requested: ['scoped', 'declined'],
  scoped: ['approved', 'declined'],
  approved: ['building', 'declined'],
  building: ['delivered', 'declined'],
  delivered: [],
  declined: [],
};

const STATUS_BADGE: Record<BespokeStatus, BadgeVariant> = {
  requested: 'neutral', scoped: 'violet', approved: 'teal',
  building: 'amber', delivered: 'success', declined: 'danger',
};
const PRIORITY_BADGE: Record<Priority, BadgeVariant> = {
  vip: 'teal', high: 'amber', medium: 'neutral', low: 'neutral',
};
const ALL_STATUSES: BespokeStatus[] = ['requested', 'scoped', 'approved', 'building', 'delivered', 'declined'];

const SUBNAV = [
  { label: 'Customize', href: '/platform-console' },
  { label: 'Bespoke Atelier', href: '/platform-console/bespoke' },
  { label: 'Ops & Readiness', href: '/platform-console/ops' },
] as const;

function ConsoleSubnav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Platform Console sections" className="flex flex-wrap gap-2 mb-6">
      {SUBNAV.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? 'page' : undefined}
            className={
              active
                ? 'px-4 py-1.5 rounded-full text-sm font-semibold bg-teal-600 text-white shadow-card'
                : 'px-4 py-1.5 rounded-full text-sm font-medium text-ink-muted bg-surface border border-line hover:text-ink hover:bg-surface-2 transition-colors'
            }
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default function BespokePage() {
  const { user, authFetch } = useAuth();
  const { show } = useToast();
  const isDev = Boolean(user?.is_platform_developer);

  const [requests, setRequests] = useState<BespokeRequest[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<'' | BespokeStatus>('');

  // Detail modal
  const [selected, setSelected] = useState<BespokeRequest | null>(null);
  const [moveTo, setMoveTo] = useState<'' | BespokeStatus>('');
  const [notes, setNotes] = useState('');
  const [estimate, setEstimate] = useState('');
  const [priority, setPriority] = useState<Priority>('medium');
  const [saving, setSaving] = useState(false);

  // Create modal
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ tenant_id: '', title: '', client_description: '', priority: 'medium' as Priority });

  const loadRequests = useCallback(async () => {
    setLoading(true);
    try {
      const q = statusFilter ? `?status=${statusFilter}` : '';
      const res = await authFetch(`/api/admin/dev/bespoke${q}`);
      setRequests(res.ok ? (await res.json()).requests ?? [] : []);
    } catch {
      setRequests([]);
    } finally {
      setLoading(false);
    }
  }, [authFetch, statusFilter]);

  const loadTenants = useCallback(async () => {
    try {
      const res = await authFetch('/api/tenants');
      if (res.ok) setTenants((await res.json()).tenants ?? []);
    } catch { /* tenant context is optional */ }
  }, [authFetch]);

  useEffect(() => { if (isDev) { loadRequests(); loadTenants(); } }, [isDev, loadRequests, loadTenants]);

  const openDetail = (r: BespokeRequest) => {
    setSelected(r);
    setMoveTo('');
    setNotes(r.scoping_notes ?? '');
    setEstimate(r.estimate ?? '');
    setPriority(r.priority);
  };

  const saveDetail = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = { priority, scoping_notes: notes || null, estimate: estimate || null };
      if (moveTo) body.status = moveTo;
      const res = await authFetch(`/api/admin/dev/bespoke/${selected.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        show('Request updated', { variant: 'success' });
        setSelected(null);
        await loadRequests();
      } else {
        const err = await res.json().catch(() => ({}));
        show(typeof err.detail === 'string' ? err.detail : 'Update rejected', { variant: 'error' });
      }
    } catch {
      show('Update rejected — network error', { variant: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const createRequest = async () => {
    if (form.title.trim().length < 3 || form.client_description.trim().length < 3) {
      show('Title and description are required', { variant: 'error' });
      return;
    }
    setSaving(true);
    try {
      const res = await authFetch('/api/admin/dev/bespoke', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: form.tenant_id ? Number(form.tenant_id) : undefined,
          title: form.title.trim(),
          client_description: form.client_description.trim(),
          priority: form.priority,
        }),
      });
      if (res.ok) {
        show('Bespoke request filed', { variant: 'success' });
        setCreating(false);
        setForm({ tenant_id: '', title: '', client_description: '', priority: 'medium' });
        await loadRequests();
      } else {
        const err = await res.json().catch(() => ({}));
        show(typeof err.detail === 'string' ? err.detail : 'Could not file request', { variant: 'error' });
      }
    } catch {
      show('Could not file request — network error', { variant: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const tenantName = (id: number | null) =>
    id == null ? '—' : (tenants.find((t) => t.id === id)?.name ?? `#${id}`);

  if (!isDev) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-7xl mx-auto">
          <Card padding="none">
            <NoPermissionState
              title="Platform developer access required"
              description="This internal console is only for the platform team."
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
          eyebrow="Internal"
          title="Bespoke Atelier"
          description="What clients asked for that the product doesn't do yet — tracked from request to delivery."
        />
        <ConsoleSubnav />

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Ledger */}
          <div className="lg:col-span-3 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div className="w-56">
                <Select
                  label="Status"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as '' | BespokeStatus)}
                >
                  <option value="">All statuses</option>
                  {ALL_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </Select>
              </div>
              <Button onClick={() => setCreating(true)} className="mt-7">New request</Button>
            </div>

            {loading ? (
              <SkeletonCard />
            ) : requests.length === 0 ? (
              <Card padding="none">
                <EmptyState
                  title="No bespoke requests yet"
                  description="When a client asks for something we don't have, file it here."
                />
              </Card>
            ) : (
              <Card padding="none" className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <Th>Title</Th><Th>Tenant</Th><Th>Priority</Th><Th>Status</Th><Th>Created</Th>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {requests.map((r) => (
                      <TableRow key={r.id} onClick={() => openDetail(r)} className="cursor-pointer hover:bg-surface-2">
                        <Td className="font-medium text-ink">{r.title}</Td>
                        <Td className="text-ink-soft">{tenantName(r.tenant_id)}</Td>
                        <Td><Badge variant={PRIORITY_BADGE[r.priority]}>{r.priority}</Badge></Td>
                        <Td><Badge variant={STATUS_BADGE[r.status]}>{r.status}</Badge></Td>
                        <Td className="text-ink-muted text-sm">{r.created_at?.slice(0, 10)}</Td>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Card>
            )}
          </div>

          {/* Atelier advisor */}
          <div className="lg:col-span-2">
            <AtelierChat tenants={tenants} onFiled={loadRequests} />
          </div>
        </div>
      </div>

      {/* Detail / transition modal */}
      <Modal open={Boolean(selected)} onClose={() => setSelected(null)} title={selected?.title} size="md">
        {selected && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Badge variant={STATUS_BADGE[selected.status]}>{selected.status}</Badge>
              <span className="text-sm text-ink-muted">Tenant: {tenantName(selected.tenant_id)}</span>
            </div>
            <p className="text-sm text-ink-soft whitespace-pre-wrap">{selected.client_description}</p>

            <Select label="Priority" value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
              {(['low', 'medium', 'high', 'vip'] as Priority[]).map((p) => <option key={p} value={p}>{p}</option>)}
            </Select>

            <div>
              <label className="block text-sm font-medium text-ink-soft mb-2">Scoping notes / decline reason</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-teal-400"
              />
            </div>

            <Input label="Estimate" value={estimate} onChange={(e) => setEstimate(e.target.value)} placeholder="e.g. 2 weeks / 40h" />

            {TRANSITIONS[selected.status].length > 0 ? (
              <Select label="Move to" value={moveTo} onChange={(e) => setMoveTo(e.target.value as '' | BespokeStatus)}>
                <option value="">— keep {selected.status} —</option>
                {TRANSITIONS[selected.status].map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
            ) : (
              <p className="text-sm text-ink-muted">This request is {selected.status} (terminal) — no further transitions.</p>
            )}
            {moveTo === 'declined' && !notes.trim() && (
              <p className="text-xs text-danger">A decline reason (scoping notes) is required.</p>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setSelected(null)}>Cancel</Button>
              <Button onClick={saveDetail} loading={saving} disabled={moveTo === 'declined' && !notes.trim()}>Save</Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Create modal */}
      <Modal open={creating} onClose={() => setCreating(false)} title="New bespoke request" size="md">
        <div className="space-y-4">
          {tenants.length > 0 ? (
            <Select label="Tenant (optional)" value={form.tenant_id} onChange={(e) => setForm((f) => ({ ...f, tenant_id: e.target.value }))}>
              <option value="">No tenant</option>
              {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </Select>
          ) : (
            <Input label="Tenant id (optional)" type="number" value={form.tenant_id} onChange={(e) => setForm((f) => ({ ...f, tenant_id: e.target.value }))} />
          )}
          <Input label="Title" value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
          <div>
            <label className="block text-sm font-medium text-ink-soft mb-2">What the client wants</label>
            <textarea
              value={form.client_description}
              onChange={(e) => setForm((f) => ({ ...f, client_description: e.target.value }))}
              rows={4}
              className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-teal-400"
            />
          </div>
          <Select label="Priority" value={form.priority} onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value as Priority }))}>
            {(['low', 'medium', 'high', 'vip'] as Priority[]).map((p) => <option key={p} value={p}>{p}</option>)}
          </Select>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button onClick={createRequest} loading={saving}>File request</Button>
          </div>
        </div>
      </Modal>
    </main>
  );
}
