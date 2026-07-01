'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import {
  PageHeader, Card, Badge, Button, Input, Select, SkeletonCard, useToast, Stagger, RevealItem,
} from '@/components/ui';
import type { BadgeVariant } from '@/components/ui';
import { apiGet, apiPost, ApiError } from '@/lib/apiClient';
import { Users, UserPlus, ShieldAlert, Copy } from 'lucide-react';

const ROLE_LABEL: Record<string, string> = {
  super_admin: 'Admin', regional_manager: 'Regional manager', store_manager: 'Store manager', analyst: 'Analyst',
};
const STATUS_TONE: Record<string, BadgeVariant> = { active: 'success', inactive: 'neutral', locked: 'danger', pending: 'amber' };

interface Member { id: number; email: string; first_name: string; last_name: string;
  role: string; status: string; last_login_at: string | null; is_self: boolean; }
interface Seats { plan: string; used: number; limit: number | null; remaining: number | null; over: boolean; }

export default function TeamPage() {
  const { user, authFetch } = useAuth();
  const { show } = useToast();
  const isAdmin = ['super_admin', 'admin'].includes(user?.role ?? '');

  const [members, setMembers] = useState<Member[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [seats, setSeats] = useState<Seats | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState({ email: '', first_name: '', last_name: '', role: 'analyst' });
  const [inviteLink, setInviteLink] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [t, s] = await Promise.all([
        apiGet<{ members: Member[]; assignable_roles: string[] }>('/api/team'),
        apiGet<Seats>('/api/team/seats'),
      ]);
      setMembers(t.members ?? []); setRoles(t.assignable_roles ?? []); setSeats(s);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);
  useEffect(() => { if (isAdmin) load(); else setLoading(false); }, [isAdmin, load]);

  const patch = async (path: string, body: object) => {
    const res = await authFetch(path, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) { const e = await res.json().catch(() => ({})); show(e.detail || 'Update failed', { variant: 'error' }); return false; }
    return true;
  };

  const setRole = async (m: Member, role: string) => {
    setBusy(true);
    if (await patch(`/api/team/${m.id}/role`, { role })) { show('Role updated', { variant: 'success' }); await load(); }
    setBusy(false);
  };
  const toggleStatus = async (m: Member) => {
    setBusy(true);
    const next = m.status === 'active' ? 'inactive' : 'active';
    if (await patch(`/api/team/${m.id}/status`, { status: next })) { show(`Member ${next === 'active' ? 'enabled' : 'disabled'}`, { variant: 'success' }); await load(); }
    setBusy(false);
  };

  const sendInvite = async () => {
    if (!invite.email || !invite.first_name || !invite.last_name) { show('Fill in name and email', { variant: 'error' }); return; }
    setBusy(true); setInviteLink('');
    try {
      const res = await apiPost<{ accept_link?: string }>('/api/auth/invite', invite);
      setInviteLink(res.accept_link ?? '');
      show('Invite created', { variant: 'success' });
      setInvite({ email: '', first_name: '', last_name: '', role: 'analyst' });
      await load();
    } catch (e) { show(e instanceof ApiError ? e.message : 'Invite failed', { variant: 'error' }); }
    finally { setBusy(false); }
  };

  if (!isAdmin) {
    return (
      <main className="min-h-screen p-4 md:p-8"><div className="max-w-3xl mx-auto">
        <Card padding="lg" className="text-center">
          <ShieldAlert className="w-8 h-8 text-amber-500 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-ink">Admin access required</h2>
        </Card>
      </div></main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        <PageHeader title="Team" description="Invite teammates, set roles, and manage access." icon={<Users className="w-5 h-5" />} />

        {loading ? <div className="space-y-4"><SkeletonCard /><SkeletonCard /></div> : (
          <Stagger className="space-y-6">
            {seats && (
              <RevealItem><Card padding="lg">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Seats</h3>
                  <Badge variant={seats.over ? 'coral' : 'teal'}>{seats.plan} plan</Badge>
                </div>
                <p className="text-sm text-ink">{seats.used}{seats.limit == null ? ' · unlimited' : ` / ${seats.limit} seats used`}</p>
                {seats.limit != null && (
                  <div className="h-2 rounded-full bg-ink/5 overflow-hidden mt-2">
                    <div className={`h-full rounded-full ${seats.over ? 'bg-coral-500' : 'bg-teal-500'}`}
                      style={{ width: `${Math.min(100, (seats.used / seats.limit) * 100)}%` }} />
                  </div>
                )}
              </Card></RevealItem>
            )}

            {/* Invite */}
            <RevealItem><Card padding="lg">
              <div className="flex items-center gap-2 mb-4"><UserPlus className="w-4 h-4 text-teal-600" />
                <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Invite a teammate</h3></div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Input label="First name" value={invite.first_name} onChange={(e) => setInvite({ ...invite, first_name: e.target.value })} />
                <Input label="Last name" value={invite.last_name} onChange={(e) => setInvite({ ...invite, last_name: e.target.value })} />
                <Input label="Email" type="email" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
                <Select label="Role" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
                  {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
                </Select>
              </div>
              <div className="mt-4"><Button onClick={sendInvite} disabled={busy}><UserPlus className="w-4 h-4 me-1.5" /> Send invite</Button></div>
              {inviteLink && (
                <div className="mt-3 flex items-center gap-2 rounded-xl bg-surface-2/60 p-3">
                  <code className="flex-1 text-xs break-all text-ink-soft">{inviteLink}</code>
                  <Button variant="ghost" size="sm" onClick={() => { navigator.clipboard?.writeText(inviteLink); show('Copied', { variant: 'success' }); }}>
                    <Copy className="w-4 h-4" />
                  </Button>
                </div>
              )}
            </Card></RevealItem>

            {/* Members */}
            <RevealItem><Card padding="lg">
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Members ({members.length})</h3>
              <div className="space-y-2">
                {members.map((m) => (
                  <div key={m.id} className="flex items-center gap-3 rounded-xl border border-line p-3 flex-wrap">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-ink truncate">{m.first_name} {m.last_name}{m.is_self && <span className="text-xs text-ink-muted"> (you)</span>}</p>
                      <p className="text-xs text-ink-muted truncate">{m.email} · last login {m.last_login_at ? new Date(m.last_login_at).toLocaleDateString() : 'never'}</p>
                    </div>
                    <Badge variant={STATUS_TONE[m.status] ?? 'neutral'}>{m.status}</Badge>
                    <Select value={m.role} disabled={m.is_self || busy} onChange={(e) => setRole(m, e.target.value)} className="w-44">
                      {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
                    </Select>
                    {!m.is_self && (
                      <Button variant="secondary" size="sm" disabled={busy} onClick={() => toggleStatus(m)}>
                        {m.status === 'active' ? 'Disable' : 'Enable'}
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            </Card></RevealItem>
          </Stagger>
        )}
      </div>
    </main>
  );
}
