'use client';

/**
 * Atelier chat (Platform Console, internal).
 *
 * A developer describes what a client wants in plain language; the backend
 * (/api/ai/atelier/suggest) maps it onto the customization catalog and returns
 * bespoke-work drafts for anything the product can't express. The response is
 * rendered HONESTLY: an `engine` badge says whether an LLM answered ('llm', with
 * the model) or the deterministic rule-based fallback did ('rules', LLM offline)
 * — a suggestion is never dressed up as AI when it wasn't.
 */

import { useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { Card, Button, Badge, useToast } from '@/components/ui';

interface Suggestion {
  key: string;
  value: boolean | string | number;
  reason: string;
  available: boolean;
}
interface Gap {
  title: string;
  why: string;
  draft_request: { title: string; client_description: string; priority: string };
}
interface AtelierResult {
  engine: 'llm' | 'rules';
  model: string | null;
  summary: string;
  suggestions: Suggestion[];
  gaps: Gap[];
}
type ThreadEntry =
  | { role: 'you'; text: string }
  | { role: 'atelier'; result?: AtelierResult; error?: string };

interface AtelierChatProps {
  tenants: { id: number; name: string }[];
  onFiled: () => void;
}

export default function AtelierChat({ tenants, onFiled }: AtelierChatProps) {
  const { authFetch } = useAuth();
  const { show } = useToast();
  const [thread, setThread] = useState<ThreadEntry[]>([]);
  const [description, setDescription] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [busy, setBusy] = useState(false);
  const [filing, setFiling] = useState<string | null>(null);

  const send = async () => {
    const text = description.trim();
    if (text.length < 3 || busy) return;
    setBusy(true);
    setThread((t) => [...t, { role: 'you', text }]);
    setDescription('');
    try {
      const res = await authFetch('/api/ai/atelier/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: text, tenant_id: tenantId ? Number(tenantId) : undefined }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = typeof err.detail === 'string' ? err.detail : `Advisor unavailable (HTTP ${res.status})`;
        setThread((t) => [...t, { role: 'atelier', error: msg }]);
        show(msg, { variant: 'error' });
        return;
      }
      const result: AtelierResult = await res.json();
      setThread((t) => [...t, { role: 'atelier', result }]);
    } catch {
      const msg = 'The advisor backend is not reachable.';
      setThread((t) => [...t, { role: 'atelier', error: msg }]);
      show(msg, { variant: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const fileGap = async (gap: Gap) => {
    setFiling(gap.title);
    try {
      const res = await authFetch('/api/admin/dev/bespoke', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: tenantId ? Number(tenantId) : undefined,
          title: gap.draft_request.title,
          client_description: gap.draft_request.client_description,
          priority: gap.draft_request.priority || 'medium',
        }),
      });
      if (res.ok) {
        show('Filed as a bespoke request', { variant: 'success' });
        onFiled();
      } else {
        const err = await res.json().catch(() => ({}));
        show(typeof err.detail === 'string' ? err.detail : 'Could not file request', { variant: 'error' });
      }
    } catch {
      show('Could not file request — network error', { variant: 'error' });
    } finally {
      setFiling(null);
    }
  };

  const copyKey = (key: string) => {
    navigator.clipboard?.writeText(key).then(
      () => show(`Copied ${key}`, { variant: 'success' }),
      () => show('Copy failed', { variant: 'error' }),
    );
  };

  return (
    <Card padding="md" className="flex flex-col h-full min-h-[28rem]">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-ink">Atelier Advisor</h2>
        {tenants.length > 0 && (
          <select
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            className="text-xs rounded-lg border border-line bg-surface px-2 py-1 text-ink-soft"
            aria-label="Tenant context"
          >
            <option value="">No tenant context</option>
            {tenants.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-3 pe-1">
        {thread.length === 0 && (
          <p className="text-sm text-ink-muted">
            Describe what the client wants in plain language — you&apos;ll get catalog settings
            that cover it, and bespoke-work drafts for whatever we don&apos;t have yet.
          </p>
        )}
        {thread.map((entry, i) =>
          entry.role === 'you' ? (
            <div key={i} className="text-sm text-ink bg-surface-2 rounded-xl px-3 py-2 ms-6">
              {entry.text}
            </div>
          ) : (
            <div key={i} className="text-sm rounded-xl border border-line bg-surface px-3 py-3 me-6 space-y-3">
              {entry.error ? (
                <p className="text-danger">{entry.error}</p>
              ) : entry.result ? (
                <>
                  <div className="flex items-center gap-2">
                    {entry.result.engine === 'llm' ? (
                      <Badge variant="teal" title="Answered by the local AI model">
                        AI{entry.result.model ? ` · ${entry.result.model}` : ''}
                      </Badge>
                    ) : (
                      <Badge variant="neutral" title="The LLM was unavailable; this is the deterministic keyword mapper, not AI.">
                        rule-based (LLM offline)
                      </Badge>
                    )}
                    <span className="text-ink-soft">{entry.result.summary}</span>
                  </div>

                  {entry.result.suggestions.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">Configure</p>
                      <ul className="space-y-1.5">
                        {entry.result.suggestions.map((s, j) => (
                          <li key={j} className="flex items-start gap-2">
                            <button
                              onClick={() => copyKey(s.key)}
                              title="Copy catalog key"
                              className="font-mono text-xs bg-surface-2 rounded px-1.5 py-0.5 text-teal-700 hover:bg-surface-3 shrink-0"
                            >
                              {s.key}
                            </button>
                            <span className="text-ink-soft">
                              → <span className="font-medium text-ink">{String(s.value)}</span>
                              {!s.available && <Badge variant="warning" className="ms-1">unavailable</Badge>}
                              <span className="block text-xs text-ink-muted">{s.reason}</span>
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {entry.result.gaps.length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-1">
                        Doesn&apos;t exist yet
                      </p>
                      <ul className="space-y-2">
                        {entry.result.gaps.map((g, j) => (
                          <li key={j} className="flex items-start justify-between gap-2">
                            <span className="text-ink-soft">
                              <span className="font-medium text-ink">{g.title}</span>
                              <span className="block text-xs text-ink-muted">{g.why}</span>
                            </span>
                            <Button
                              size="sm"
                              variant="secondary"
                              loading={filing === g.title}
                              onClick={() => fileGap(g)}
                            >
                              File as bespoke
                            </Button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : null}
            </div>
          ),
        )}
      </div>

      <div className="mt-3 border-t border-line pt-3">
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); send(); } }}
          rows={3}
          placeholder="e.g. They want scheduled SFTP imports and a POS integration, and they asked for a Slack digest of daily findings."
          className="w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:ring-2 focus:ring-teal-400"
        />
        <div className="flex items-center justify-between mt-2">
          <span className="text-xs text-ink-muted">⌘/Ctrl + Enter to send</span>
          <Button size="sm" onClick={send} loading={busy} disabled={description.trim().length < 3}>
            Ask the Atelier
          </Button>
        </div>
      </div>
    </Card>
  );
}
