'use client';

/**
 * Developer Portal (full PaaS surface): API keys (scoped) + usage analytics,
 * webhooks + delivery log, an interactive try-it playground with code snippets,
 * a live "Ask Sage" box, an embeddable widget generator, and the API reference.
 * Public endpoints are exercised with the tenant's API key; management endpoints
 * use the authed session.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Code2, Plus, Trash2, Send, Copy, KeyRound, Webhook, ExternalLink, Play,
  Sparkles, Boxes, Activity, ChevronDown, ChevronRight,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Button, Badge, Input, StatCard } from '@/components/ui';
import {
  ApiKey, Hook, Delivery, PublicEndpoint, PUBLIC_ENDPOINTS,
  curlSnippet, jsSnippet, pythonSnippet, embedSnippet,
} from './helpers';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const ALL_SCOPES = ['read', 'write'] as const;

type Tab = 'overview' | 'keys' | 'webhooks' | 'playground' | 'embed' | 'reference';
const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <Activity className="w-4 h-4" /> },
  { id: 'keys', label: 'API Keys', icon: <KeyRound className="w-4 h-4" /> },
  { id: 'webhooks', label: 'Webhooks', icon: <Webhook className="w-4 h-4" /> },
  { id: 'playground', label: 'Playground', icon: <Play className="w-4 h-4" /> },
  { id: 'embed', label: 'Embed Sage', icon: <Sparkles className="w-4 h-4" /> },
  { id: 'reference', label: 'API Reference', icon: <Boxes className="w-4 h-4" /> },
];

export default function DevelopersPage() {
  const { authFetch } = useAuth();
  const [tab, setTab] = useState<Tab>('overview');
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [hooks, setHooks] = useState<Hook[]>([]);
  const [usage, setUsage] = useState<PlanUsage | null>(null);
  const [periodUsage, setPeriodUsage] = useState<PeriodUsage | null>(null);
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [msg, setMsg] = useState('');
  // The most recently created key, kept in memory so the playground/embed can use
  // it immediately (the full key is only ever returned once, at creation).
  const [liveKey, setLiveKey] = useState('');

  const load = useCallback(async () => {
    try {
      const [k, w, u, p] = await Promise.all([
        authFetch('/api/api-keys'), authFetch('/api/webhooks'), authFetch('/api/tenants/usage'),
        authFetch('/api/tenants/usage/period'),
      ]);
      if (k.ok) setKeys((await k.json()).keys ?? []);
      if (w.ok) setHooks((await w.json()).webhooks ?? []);
      if (u.ok) setUsage(await u.json());
      if (p.ok) setPeriodUsage(await p.json());
    } catch { /* ignore */ }
  }, [authFetch]);
  useEffect(() => { load(); }, [load]);

  const flash = (m: string) => { setMsg(m); setTimeout(() => setMsg(''), 4000); };
  const copy = (v: string) => { try { navigator.clipboard?.writeText(v); flash('Copied to clipboard.'); } catch { /* */ } };

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        <PageHeader
          title="Developer Portal"
          description="API keys, webhooks, a live playground, and an embeddable Sage widget for your tenant."
          icon={<Code2 className="w-6 h-6" />}
          actions={
            <a href={`${API_BASE}/docs`} target="_blank" rel="noreferrer">
              <Button variant="secondary"><ExternalLink className="w-4 h-4" /> Swagger</Button>
            </a>
          }
        />

        {msg && <div className="p-3 rounded-xl bg-teal-50 border border-teal-200 text-teal-800 text-sm">{msg}</div>}
        {secret && (
          <div className="p-4 rounded-xl bg-amber-50 border border-amber-300">
            <p className="text-sm font-medium text-amber-800 mb-2">{secret.label} — copy it now, you won&apos;t see it again:</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 px-3 py-2 rounded-lg bg-surface border border-amber-200 text-xs break-all">{secret.value}</code>
              <Button variant="ghost" size="sm" onClick={() => copy(secret.value)}><Copy className="w-4 h-4" /></Button>
              <Button variant="ghost" size="sm" onClick={() => setSecret(null)}>Dismiss</Button>
            </div>
          </div>
        )}

        {/* Tab nav */}
        <div className="flex flex-wrap gap-1 border-b border-line">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.id ? 'border-teal-500 text-teal-700' : 'border-transparent text-ink-muted hover:text-ink'
              }`}
            >
              {t.icon}{t.label}
            </button>
          ))}
        </div>

        {tab === 'overview' && <Overview keys={keys} hooks={hooks} usage={usage} periodUsage={periodUsage} />}
        {tab === 'keys' && (
          <KeysPanel keys={keys} authFetch={authFetch} reload={load}
            onSecret={(v) => { setSecret({ label: 'API key (shown once)', value: v }); setLiveKey(v); }} onErr={flash} />
        )}
        {tab === 'webhooks' && (
          <WebhooksPanel hooks={hooks} authFetch={authFetch} reload={load}
            onSecret={(v) => setSecret({ label: 'Webhook signing secret (shown once)', value: v })} onMsg={flash} />
        )}
        {tab === 'playground' && <Playground liveKey={liveKey} setLiveKey={setLiveKey} onCopy={copy} />}
        {tab === 'embed' && <EmbedPanel liveKey={liveKey} setLiveKey={setLiveKey} onCopy={copy} />}
        {tab === 'reference' && <Reference />}
      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
function Overview({ keys, hooks, usage, periodUsage }: { keys: ApiKey[]; hooks: Hook[]; usage: PlanUsage | null; periodUsage: PeriodUsage | null }) {
  const totalReq = keys.reduce((s, k) => s + (k.request_count || 0), 0);
  const activeKeys = keys.filter((k) => !k.revoked).length;
  const activeHooks = hooks.filter((h) => h.active).length;
  const maxReq = Math.max(1, ...keys.map((k) => k.request_count || 0));
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="API keys" value={String(activeKeys)} tone="teal" />
        <StatCard label="Total API requests" value={totalReq.toLocaleString()} tone="violet" />
        <StatCard label="Webhooks" value={String(activeHooks)} tone="coral" />
        <StatCard label="Public endpoints" value={String(PUBLIC_ENDPOINTS.length)} tone="amber" />
      </div>
      {usage && <PlanUsageCard usage={usage} />}
      {periodUsage && <BillingPeriodCard usage={periodUsage} />}
      <Card padding="lg">
        <h3 className="text-base font-medium text-ink mb-4">Requests by key</h3>
        {keys.length === 0 ? <p className="text-sm text-ink-muted">No API keys yet — create one under the API Keys tab.</p> : (
          <div className="space-y-3">
            {keys.map((k) => (
              <div key={k.id} className="flex items-center gap-3">
                <div className="w-40 truncate text-sm text-ink">{k.name}</div>
                <div className="flex-1 h-3 rounded-full bg-ink/5 overflow-hidden">
                  <div className="h-full rounded-full bg-teal-500" style={{ width: `${((k.request_count || 0) / maxReq) * 100}%` }} />
                </div>
                <div className="w-24 text-end text-sm text-ink-soft">{(k.request_count || 0).toLocaleString()}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

// --- Plan & usage metering (Track 5) ---------------------------------------
type Meter = { used: number; limit: number | null; remaining: number | null; over_quota: boolean; pct: number };
type PlanUsage = {
  plan: string;
  window: string;
  any_over_quota: boolean;
  usage: { api_requests: Meter; api_keys: Meter; users: Meter };
};

const METER_LABELS: { key: keyof PlanUsage['usage']; label: string }[] = [
  { key: 'api_requests', label: 'API requests' },
  { key: 'api_keys', label: 'API keys' },
  { key: 'users', label: 'Users' },
];

function PlanUsageCard({ usage }: { usage: PlanUsage }) {
  return (
    <Card padding="lg">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-medium text-ink">Plan &amp; usage</h3>
        <Badge variant={usage.any_over_quota ? 'coral' : 'teal'}>
          {usage.plan.charAt(0).toUpperCase() + usage.plan.slice(1)} plan
        </Badge>
      </div>
      <div className="space-y-4">
        {METER_LABELS.map(({ key, label }) => {
          const m = usage.usage[key];
          const unlimited = m.limit === null;
          const pct = unlimited ? 0 : Math.min(100, m.pct);
          const bar = m.over_quota ? 'bg-coral-500' : pct > 80 ? 'bg-amber-500' : 'bg-teal-500';
          return (
            <div key={key}>
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="text-ink">{label}</span>
                <span className="text-ink-soft">
                  {m.used.toLocaleString()}{unlimited ? ' · unlimited' : ` / ${m.limit!.toLocaleString()}`}
                </span>
              </div>
              <div className="h-2.5 rounded-full bg-ink/5 overflow-hidden">
                <div className={`h-full rounded-full ${bar}`} style={{ width: unlimited ? '100%' : `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-4 text-xs text-ink-muted">
        Metering only — usage is shown so plan limits are visible; nothing is billed.
        Counts are {usage.window} totals.
      </p>
    </Card>
  );
}

// --- Billing-period usage metering (Phase 3) -------------------------------
type PeriodUsage = {
  plan: string;
  window: string;
  enforced: boolean;
  any_over_quota: boolean;
  usage: { sage_messages: Meter; forecast_jobs: Meter; exports: Meter; imports: Meter; api_requests: Meter };
};

const PERIOD_LABELS: { key: keyof PeriodUsage['usage']; label: string }[] = [
  { key: 'sage_messages', label: 'Sage messages' },
  { key: 'forecast_jobs', label: 'Forecast jobs' },
  { key: 'exports', label: 'Exports' },
  { key: 'imports', label: 'Imports' },
  { key: 'api_requests', label: 'API requests' },
];

function BillingPeriodCard({ usage }: { usage: PeriodUsage }) {
  return (
    <Card padding="lg">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-medium text-ink">This billing period</h3>
        <Badge variant={usage.any_over_quota ? 'coral' : 'teal'}>{usage.window}</Badge>
      </div>
      <div className="space-y-4">
        {PERIOD_LABELS.map(({ key, label }) => {
          const m = usage.usage[key];
          const unlimited = m.limit === null;
          const pct = unlimited ? 0 : Math.min(100, m.pct);
          const bar = m.over_quota ? 'bg-coral-500' : pct > 80 ? 'bg-amber-500' : 'bg-teal-500';
          return (
            <div key={key}>
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="text-ink">{label}</span>
                <span className="text-ink-soft">
                  {m.used.toLocaleString()}{unlimited ? ' · unlimited' : ` / ${m.limit!.toLocaleString()}`}
                </span>
              </div>
              <div className="h-2.5 rounded-full bg-ink/5 overflow-hidden">
                <div className={`h-full rounded-full ${bar}`} style={{ width: unlimited ? '100%' : `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-4 text-xs text-ink-muted">
        Calendar month (Asia/Dubai). {usage.enforced
          ? 'Quotas are enforced — over-limit actions are blocked.'
          : 'Metering only — nothing is blocked or billed yet.'}
      </p>
    </Card>
  );
}

// ---------------------------------------------------------------------------
type AuthFetch = ReturnType<typeof useAuth>['authFetch'];

function KeysPanel({ keys, authFetch, reload, onSecret, onErr }:
  { keys: ApiKey[]; authFetch: AuthFetch; reload: () => void; onSecret: (v: string) => void; onErr: (m: string) => void }) {
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<string[]>(['read']);

  const toggle = (s: string) => setScopes((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]);
  const create = async () => {
    if (!name.trim()) return;
    const res = await authFetch('/api/api-keys', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, scopes: scopes.length ? scopes : ['read'] }),
    });
    const d = await res.json();
    if (res.ok) { onSecret(d.api_key); setName(''); reload(); } else onErr(d.message || 'Failed to create key');
  };
  const revoke = async (id: number) => { await authFetch(`/api/api-keys/${id}`, { method: 'DELETE' }); reload(); };

  return (
    <Card padding="lg">
      <div className="flex items-center gap-2 mb-4"><KeyRound className="w-5 h-5 text-ink-muted" /><h3 className="text-base font-medium text-ink">API Keys</h3></div>
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Key name (e.g. Reporting bot)" className="flex-1 min-w-[200px]" />
        <div className="flex items-center gap-2">
          {ALL_SCOPES.map((s) => (
            <button key={s} onClick={() => toggle(s)}
              className={`px-2.5 py-1.5 rounded-lg text-xs font-medium border ${scopes.includes(s) ? 'bg-teal-50 border-teal-300 text-teal-700' : 'border-line text-ink-muted'}`}>
              {s}
            </button>
          ))}
        </div>
        <Button variant="primary" size="sm" onClick={create}><Plus className="w-4 h-4" /> Create key</Button>
      </div>
      {keys.length === 0 ? <p className="text-sm text-ink-muted">No API keys yet.</p> : (
        <table className="w-full text-sm">
          <thead><tr className="text-start text-ink-muted border-b border-line">
            <th className="py-2 pe-4 font-medium">Prefix</th><th className="py-2 pe-4 font-medium">Name</th>
            <th className="py-2 pe-4 font-medium">Scopes</th><th className="py-2 pe-4 font-medium text-end">Requests</th>
            <th className="py-2 pe-4 font-medium">Last used</th><th className="py-2 font-medium text-end">Action</th></tr></thead>
          <tbody>{keys.map((k) => (
            <tr key={k.id} className="border-b border-line/60">
              <td className="py-2.5 pe-4 font-mono text-ink">{k.key_prefix}…</td>
              <td className="py-2.5 pe-4 text-ink">{k.name}</td>
              <td className="py-2.5 pe-4">{k.scopes.map((s) => <Badge key={s} variant="teal">{s}</Badge>)}</td>
              <td className="py-2.5 pe-4 text-end text-ink">{(k.request_count || 0).toLocaleString()}</td>
              <td className="py-2.5 pe-4 text-ink-muted text-xs">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : 'never'}</td>
              <td className="py-2.5 text-end">{k.revoked ? <Badge variant="danger">revoked</Badge> : <Button variant="ghost" size="sm" onClick={() => revoke(k.id)}><Trash2 className="w-4 h-4" /></Button>}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
function WebhooksPanel({ hooks, authFetch, reload, onSecret, onMsg }:
  { hooks: Hook[]; authFetch: AuthFetch; reload: () => void; onSecret: (v: string) => void; onMsg: (m: string) => void }) {
  const [url, setUrl] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);
  const [deliveries, setDeliveries] = useState<Record<number, Delivery[]>>({});
  const [catalog, setCatalog] = useState<{ event: string; description: string }[]>([]);
  useEffect(() => {
    let active = true;
    authFetch('/api/webhooks/events').then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (active && d) setCatalog(d.events ?? []); }).catch(() => {});
    return () => { active = false; };
  }, [authFetch]);

  const create = async () => {
    if (!url.trim()) return;
    const res = await authFetch('/api/webhooks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, events: ['*'] }),
    });
    const d = await res.json();
    if (res.ok) { onSecret(d.secret); setUrl(''); reload(); } else onMsg(d.message || 'Failed to add webhook');
  };
  const del = async (id: number) => { await authFetch(`/api/webhooks/${id}`, { method: 'DELETE' }); reload(); };
  const test = async () => {
    const res = await authFetch('/api/webhooks/test', { method: 'POST' });
    const d = await res.json();
    onMsg(res.ok ? `Test event dispatched to ${d.dispatched_to} endpoint(s).` : 'Test failed');
  };
  const toggle = async (id: number) => {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    const res = await authFetch(`/api/webhooks/${id}/deliveries`);
    if (res.ok) {
      const list = (await res.json()).deliveries ?? [];
      setDeliveries((prev) => ({ ...prev, [id]: list }));
    }
  };

  return (
    <Card padding="lg">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2"><Webhook className="w-5 h-5 text-ink-muted" /><h3 className="text-base font-medium text-ink">Webhooks</h3></div>
        <Button variant="ghost" size="sm" onClick={test}><Send className="w-4 h-4" /> Send test event</Button>
      </div>
      <div className="flex gap-2 mb-4">
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://your-endpoint.com/hook" className="flex-1" />
        <Button variant="primary" size="sm" onClick={create}><Plus className="w-4 h-4" /> Add webhook</Button>
      </div>
      {hooks.length === 0 ? <p className="text-sm text-ink-muted">No webhooks yet. They fire signed POSTs on findings, action drafts, imports, billing, and procurement events — see the catalog below.</p> : (
        <div className="space-y-2">
          {hooks.map((h) => (
            <div key={h.id} className="rounded-lg border border-line/60">
              <div className="flex items-center gap-3 p-3">
                <button onClick={() => toggle(h.id)} className="text-ink-muted">{expanded === h.id ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}</button>
                <span className="flex-1 truncate text-ink text-sm">{h.url}</span>
                {h.last_status ? <Badge variant={h.last_status < 400 ? 'success' : 'danger'}>{h.last_status}</Badge> : <span className="text-ink-muted text-xs">no deliveries</span>}
                <Button variant="ghost" size="sm" onClick={() => del(h.id)}><Trash2 className="w-4 h-4" /></Button>
              </div>
              {expanded === h.id && (
                <div className="px-3 pb-3 border-t border-line/60">
                  <p className="text-xs text-ink-muted my-2">Recent deliveries</p>
                  {(deliveries[h.id]?.length ?? 0) === 0 ? <p className="text-xs text-ink-muted">No deliveries yet — use “Send test event”.</p> : (
                    <table className="w-full text-xs">
                      <tbody>{deliveries[h.id].map((d) => (
                        <tr key={d.id} className="border-b border-line/40">
                          <td className="py-1.5 pe-3 text-ink">{d.event}</td>
                          <td className="py-1.5 pe-3">{d.ok ? <Badge variant="success">{d.status_code}</Badge> : <Badge variant="danger">{d.status_code ?? 'err'}</Badge>}</td>
                          <td className="py-1.5 pe-3 text-ink-muted">{d.error ?? ''}</td>
                          <td className="py-1.5 text-end text-ink-muted">{d.delivered_at ? new Date(d.delivered_at).toLocaleString() : ''}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {catalog.length > 0 && (
        <div className="mt-6 border-t border-line/60 pt-4">
          <p className="text-xs font-medium text-ink-soft uppercase tracking-wide mb-2">Available events</p>
          <p className="text-xs text-ink-muted mb-3">Subscribe to any of these (or all). Deliveries are HMAC-signed (X-Webhook-Signature).</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {catalog.map((e) => (
              <div key={e.event} className="text-xs">
                <code className="text-teal-700">{e.event}</code>
                <span className="text-ink-muted"> — {e.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
function KeyField({ liveKey, setLiveKey }: { liveKey: string; setLiveKey: (v: string) => void }) {
  return (
    <div className="mb-4">
      <label className="block text-xs text-ink-muted mb-1">API key (created keys are filled in automatically; or paste one)</label>
      <Input value={liveKey} onChange={(e) => setLiveKey(e.target.value)} placeholder="lsk_…" className="font-mono text-xs" />
    </div>
  );
}

function Playground({ liveKey, setLiveKey, onCopy }: { liveKey: string; setLiveKey: (v: string) => void; onCopy: (v: string) => void }) {
  const [idx, setIdx] = useState(0);
  const [resp, setResp] = useState<{ status: number; body: string } | null>(null);
  const [running, setRunning] = useState(false);
  const [lang, setLang] = useState<'curl' | 'js' | 'python'>('curl');
  const ep: PublicEndpoint = PUBLIC_ENDPOINTS[idx];

  const run = async () => {
    setRunning(true); setResp(null);
    try {
      const res = await fetch(`${API_BASE}${ep.path}`, {
        method: ep.method,
        headers: { 'X-API-Key': liveKey, ...(ep.method === 'POST' ? { 'Content-Type': 'application/json' } : {}) },
        body: ep.method === 'POST' ? JSON.stringify(ep.sampleBody ?? {}) : undefined,
      });
      const text = await res.text();
      let body = text;
      try { body = JSON.stringify(JSON.parse(text), null, 2); } catch { /* keep raw */ }
      setResp({ status: res.status, body });
    } catch {
      setResp({ status: 0, body: 'Request failed (network / CORS).' });
    } finally { setRunning(false); }
  };

  const snippet = lang === 'curl' ? curlSnippet(API_BASE, ep, liveKey) : lang === 'js' ? jsSnippet(API_BASE, ep, liveKey) : pythonSnippet(API_BASE, ep, liveKey);

  return (
    <Card padding="lg">
      <h3 className="text-base font-medium text-ink mb-4">Try it</h3>
      <KeyField liveKey={liveKey} setLiveKey={setLiveKey} />
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={idx} onChange={(e) => { setIdx(Number(e.target.value)); setResp(null); }}
          className="px-3 py-2 rounded-lg border border-line bg-surface text-ink text-sm outline-none">
          {PUBLIC_ENDPOINTS.map((e, i) => <option key={e.path} value={i}>{e.method} {e.path}</option>)}
        </select>
        <Button variant="primary" size="sm" onClick={run} disabled={running || !liveKey}><Play className="w-4 h-4" /> {running ? 'Running…' : 'Run'}</Button>
        <span className="text-xs text-ink-muted">{ep.desc}</span>
      </div>
      {resp && (
        <div className="mb-4">
          <div className="flex items-center gap-2 mb-1">
            <Badge variant={resp.status >= 200 && resp.status < 300 ? 'success' : 'danger'}>HTTP {resp.status}</Badge>
          </div>
          <pre className="p-3 rounded-lg bg-ink/90 text-teal-100 text-xs overflow-auto max-h-80">{resp.body}</pre>
        </div>
      )}
      <div className="flex items-center gap-2 mb-2">
        {(['curl', 'js', 'python'] as const).map((l) => (
          <button key={l} onClick={() => setLang(l)}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium ${lang === l ? 'bg-teal-50 text-teal-700' : 'text-ink-muted hover:bg-surface-2'}`}>
            {l === 'js' ? 'JavaScript' : l === 'curl' ? 'cURL' : 'Python'}
          </button>
        ))}
        <Button variant="ghost" size="sm" className="ms-auto" onClick={() => onCopy(snippet)}><Copy className="w-4 h-4" /> Copy</Button>
      </div>
      <pre className="p-3 rounded-lg bg-ink/5 text-ink text-xs overflow-auto">{snippet}</pre>
    </Card>
  );
}

// ---------------------------------------------------------------------------
function EmbedPanel({ liveKey, setLiveKey, onCopy }: { liveKey: string; setLiveKey: (v: string) => void; onCopy: (v: string) => void }) {
  const [accent, setAccent] = useState('#0f766e');
  const [q, setQ] = useState('What was revenue last week?');
  const [answer, setAnswer] = useState('');
  const [asking, setAsking] = useState(false);

  const ask = async () => {
    if (!liveKey) { setAnswer('Add an API key first.'); return; }
    setAsking(true); setAnswer('');
    try {
      const res = await fetch(`${API_BASE}/api/public/v1/ai/ask`, {
        method: 'POST', headers: { 'X-API-Key': liveKey, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      });
      const d = await res.json();
      setAnswer(d.answer || d.detail || 'No answer.');
    } catch { setAnswer('Request failed.'); } finally { setAsking(false); }
  };

  const snippet = embedSnippet(API_BASE, liveKey, accent);

  return (
    <div className="space-y-6">
      <Card padding="lg">
        <div className="flex items-center gap-2 mb-2"><Sparkles className="w-5 h-5 text-violet-500" /><h3 className="text-base font-medium text-ink">Ask Sage (live)</h3></div>
        <p className="text-sm text-ink-muted mb-4">Calls the public <code className="text-xs">/v1/ai/ask</code> endpoint with your key — exactly what the embedded widget does.</p>
        <KeyField liveKey={liveKey} setLiveKey={setLiveKey} />
        <div className="flex gap-2">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about your data…" className="flex-1" />
          <Button variant="primary" size="sm" onClick={ask} disabled={asking}><Send className="w-4 h-4" /> {asking ? 'Asking…' : 'Ask'}</Button>
        </div>
        {answer && <div className="mt-3 p-3 rounded-lg bg-teal-50 text-teal-900 text-sm whitespace-pre-wrap">{answer}</div>}
      </Card>

      <Card padding="lg">
        <h3 className="text-base font-medium text-ink mb-2">Embeddable widget</h3>
        <p className="text-sm text-ink-muted mb-4">Drop this on any site to embed a tenant-scoped “Ask Sage” box. White-label the accent (pull name/logo/colour from <code className="text-xs">/v1/branding</code>).</p>
        <div className="flex items-center gap-3 mb-3">
          <label className="text-xs text-ink-muted">Accent</label>
          <input type="color" value={accent} onChange={(e) => setAccent(e.target.value)} className="w-8 h-8 rounded border border-line" />
          <Button variant="ghost" size="sm" className="ms-auto" onClick={() => onCopy(snippet)}><Copy className="w-4 h-4" /> Copy snippet</Button>
        </div>
        <pre className="p-3 rounded-lg bg-ink/5 text-ink text-xs overflow-auto max-h-96">{snippet}</pre>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
function Reference() {
  return (
    <Card padding="lg">
      <h3 className="text-base font-medium text-ink mb-1">Public API</h3>
      <p className="text-sm text-ink-muted mb-4">Authenticate with <code className="text-xs">X-API-Key</code> or <code className="text-xs">Authorization: Bearer &lt;key&gt;</code>. The key is the tenant scope.</p>
      <div className="space-y-2">
        {PUBLIC_ENDPOINTS.map((e) => (
          <div key={e.path} className="flex items-center gap-3 text-sm">
            <Badge variant={e.method === 'GET' ? 'teal' : 'violet'}>{e.method}</Badge>
            <code className="text-ink">{e.path}</code>
            <span className="text-ink-muted">— {e.desc}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
