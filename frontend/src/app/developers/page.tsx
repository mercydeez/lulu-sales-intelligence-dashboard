'use client';

/**
 * Developer portal (B4) — manage per-tenant API keys + webhooks and browse the
 * public API, all in-app. The plaintext key/secret is shown exactly once, at
 * creation. Pairs with the full reference in docs/PUBLIC_API.md and Swagger.
 */
import { useCallback, useEffect, useState } from 'react';
import { Code2, Plus, Trash2, Send, Copy, KeyRound, Webhook, ExternalLink } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Button, Badge } from '@/components/ui';

interface ApiKey { id: number; name: string; key_prefix: string; scopes: string[]; last_used_at: string | null; request_count: number; revoked: boolean; }
interface Hook { id: number; url: string; events: string[]; active: boolean; last_status: number | null; failure_count: number; }

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const ENDPOINTS = [
  ['GET', '/api/public/v1/kpis', 'Tenant KPIs'],
  ['GET', '/api/public/v1/forecast/projection', 'Revenue projection'],
  ['GET', '/api/public/v1/inventory/reorder-suggestions', 'Reorder suggestions'],
  ['POST', '/api/public/v1/ai/ask', 'Embeddable AI answer'],
  ['GET', '/api/public/v1/branding', 'White-label branding'],
];

export default function DevelopersPage() {
  const { authFetch } = useAuth();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [hooks, setHooks] = useState<Hook[]>([]);
  const [keyName, setKeyName] = useState('');
  const [hookUrl, setHookUrl] = useState('');
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    try {
      const [k, w] = await Promise.all([authFetch('/api/api-keys'), authFetch('/api/webhooks')]);
      if (k.ok) setKeys((await k.json()).keys ?? []);
      if (w.ok) setHooks((await w.json()).webhooks ?? []);
    } catch { /* ignore */ }
  }, [authFetch]);
  useEffect(() => { load(); }, [load]);

  const createKey = async () => {
    if (!keyName.trim()) return;
    const res = await authFetch('/api/api-keys', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: keyName, scopes: ['read'] }),
    });
    const d = await res.json();
    if (res.ok) { setSecret({ label: 'API key (shown once)', value: d.api_key }); setKeyName(''); load(); }
    else setMsg(d.message || 'Failed to create key');
  };
  const revokeKey = async (id: number) => { await authFetch(`/api/api-keys/${id}`, { method: 'DELETE' }); load(); };

  const createHook = async () => {
    if (!hookUrl.trim()) return;
    const res = await authFetch('/api/webhooks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: hookUrl, events: ['*'] }),
    });
    const d = await res.json();
    if (res.ok) { setSecret({ label: 'Webhook signing secret (shown once)', value: d.secret }); setHookUrl(''); load(); }
    else setMsg(d.message || 'Failed to add webhook');
  };
  const deleteHook = async (id: number) => { await authFetch(`/api/webhooks/${id}`, { method: 'DELETE' }); load(); };
  const testHooks = async () => {
    const res = await authFetch('/api/webhooks/test', { method: 'POST' });
    const d = await res.json();
    setMsg(res.ok ? `Test event dispatched to ${d.dispatched_to} endpoint(s).` : 'Test failed');
  };

  const copy = (v: string) => { try { navigator.clipboard?.writeText(v); setMsg('Copied to clipboard.'); } catch { /* ignore */ } };

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        <PageHeader
          title="Developer Portal"
          description="API keys, webhooks, and the public API for embedding your tenant's intelligence."
          icon={<Code2 className="w-6 h-6 text-coral-500" />}
          actions={
            <a href={`${API_BASE}/docs`} target="_blank" rel="noreferrer">
              <Button variant="secondary"><ExternalLink className="w-4 h-4" /> Swagger</Button>
            </a>
          }
        />

        {msg && <div className="p-3 rounded-xl bg-teal-50 border border-teal-200 text-teal-800 text-sm">{msg}</div>}

        {secret && (
          <div className="p-4 rounded-xl bg-amber-50 border border-amber-300">
            <p className="text-sm font-medium text-amber-800 mb-2">{secret.label} — copy it now, you won't see it again:</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 px-3 py-2 rounded-lg bg-white border border-amber-200 text-xs break-all">{secret.value}</code>
              <Button variant="ghost" size="sm" onClick={() => copy(secret.value)}><Copy className="w-4 h-4" /></Button>
              <Button variant="ghost" size="sm" onClick={() => setSecret(null)}>Dismiss</Button>
            </div>
          </div>
        )}

        {/* API Keys */}
        <Card padding="lg">
          <div className="flex items-center gap-2 mb-4"><KeyRound className="w-5 h-5 text-ink-muted" /><h3 className="text-base font-medium text-ink">API Keys</h3></div>
          <div className="flex gap-2 mb-4">
            <input value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="Key name (e.g. Reporting bot)"
              className="flex-1 px-3 py-2 rounded-lg border border-line bg-surface text-ink text-sm focus:ring-2 focus:ring-coral-400 outline-none" />
            <Button variant="primary" size="sm" onClick={createKey}><Plus className="w-4 h-4" /> Create key</Button>
          </div>
          {keys.length === 0 ? <p className="text-sm text-ink-muted">No API keys yet.</p> : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-ink-muted border-b border-line"><th className="py-2 pe-4 font-medium">Prefix</th><th className="py-2 pe-4 font-medium">Name</th><th className="py-2 pe-4 font-medium">Scopes</th><th className="py-2 pe-4 font-medium text-end">Requests</th><th className="py-2 font-medium text-end">Action</th></tr></thead>
              <tbody>{keys.map((k) => (
                <tr key={k.id} className="border-b border-line/60">
                  <td className="py-2.5 pe-4 font-mono text-ink">{k.key_prefix}…</td>
                  <td className="py-2.5 pe-4 text-ink">{k.name}</td>
                  <td className="py-2.5 pe-4">{k.scopes.map((s) => <Badge key={s} variant="teal">{s}</Badge>)}</td>
                  <td className="py-2.5 pe-4 text-end text-ink">{k.request_count}</td>
                  <td className="py-2.5 text-end">{k.revoked ? <Badge variant="danger">revoked</Badge> : <Button variant="ghost" size="sm" onClick={() => revokeKey(k.id)}><Trash2 className="w-4 h-4" /></Button>}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>

        {/* Webhooks */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2"><Webhook className="w-5 h-5 text-ink-muted" /><h3 className="text-base font-medium text-ink">Webhooks</h3></div>
            <Button variant="ghost" size="sm" onClick={testHooks}><Send className="w-4 h-4" /> Send test event</Button>
          </div>
          <div className="flex gap-2 mb-4">
            <input value={hookUrl} onChange={(e) => setHookUrl(e.target.value)} placeholder="https://your-endpoint.com/hook"
              className="flex-1 px-3 py-2 rounded-lg border border-line bg-surface text-ink text-sm focus:ring-2 focus:ring-coral-400 outline-none" />
            <Button variant="primary" size="sm" onClick={createHook}><Plus className="w-4 h-4" /> Add webhook</Button>
          </div>
          {hooks.length === 0 ? <p className="text-sm text-ink-muted">No webhooks yet. They fire signed POSTs on PO lifecycle, goods receipt, and match exceptions.</p> : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-ink-muted border-b border-line"><th className="py-2 pe-4 font-medium">URL</th><th className="py-2 pe-4 font-medium">Events</th><th className="py-2 pe-4 font-medium text-end">Last status</th><th className="py-2 font-medium text-end">Action</th></tr></thead>
              <tbody>{hooks.map((h) => (
                <tr key={h.id} className="border-b border-line/60">
                  <td className="py-2.5 pe-4 text-ink truncate max-w-xs">{h.url}</td>
                  <td className="py-2.5 pe-4 text-ink-muted">{h.events.join(', ')}</td>
                  <td className="py-2.5 pe-4 text-end">{h.last_status ? <Badge variant={h.last_status < 400 ? 'success' : 'danger'}>{h.last_status}</Badge> : <span className="text-ink-muted text-xs">—</span>}</td>
                  <td className="py-2.5 text-end"><Button variant="ghost" size="sm" onClick={() => deleteHook(h.id)}><Trash2 className="w-4 h-4" /></Button></td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>

        {/* Public API reference */}
        <Card padding="lg">
          <h3 className="text-base font-medium text-ink mb-1">Public API</h3>
          <p className="text-sm text-ink-muted mb-4">Authenticate with <code className="text-xs">Authorization: Bearer &lt;key&gt;</code> or <code className="text-xs">X-API-Key</code>. The key is the tenant scope.</p>
          <div className="space-y-2">
            {ENDPOINTS.map(([m, path, desc]) => (
              <div key={path} className="flex items-center gap-3 text-sm">
                <Badge variant={m === 'GET' ? 'teal' : 'violet'}>{m}</Badge>
                <code className="text-ink">{path}</code>
                <span className="text-ink-muted">— {desc}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 p-3 rounded-lg bg-ink/5">
            <p className="text-xs text-ink-muted mb-1">Example</p>
            <code className="text-xs text-ink break-all">curl {API_BASE}/api/public/v1/kpis -H &quot;X-API-Key: lsk_…&quot;</code>
          </div>
        </Card>
      </div>
    </main>
  );
}
