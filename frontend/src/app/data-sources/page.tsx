'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Database, Lock, Plus, RefreshCw, Trash2, CheckCircle2, AlertCircle,
  Power, Server, ShieldCheck, Circle,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import {
  PageHeader, Card, Button, Badge, Modal, Input, Select, EmptyState, useToast,
} from '@/components/ui';
import { apiGet, apiPost, apiDelete, ApiError, clearApiCache } from '@/lib/apiClient';

// ---------------------------------------------------------------------------
// Types (mirror services/data_sources.py _row_public)
// ---------------------------------------------------------------------------

type SourceType = 'builtin' | 'postgres' | 'mongo';

interface DataSource {
  id: number;
  name: string;
  type: SourceType;
  mapping: Record<string, string>;
  is_active: boolean;
  status: string | null; // 'ok' | 'error' | null
  last_tested_at: string | null;
  last_error: string | null;
  has_connection: boolean;
  created_at: string | null;
}

interface TestResult {
  ok: boolean;
  message: string;
}

const REQUIRED_FIELDS = ['date', 'store', 'item', 'quantity'] as const;
const OPTIONAL_FIELDS = ['category', 'price'] as const;
type MappingField = (typeof REQUIRED_FIELDS)[number] | (typeof OPTIONAL_FIELDS)[number];

const FIELD_HINTS: Record<MappingField, string> = {
  date: 'Transaction date column (e.g. order_date)',
  store: 'Store / branch column (e.g. store_id)',
  item: 'Product / SKU column (e.g. product_id)',
  quantity: 'Units sold column (e.g. qty)',
  category: 'Optional — product category column',
  price: 'Optional — unit price (enables revenue, not just units)',
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DataSourcesPage() {
  const { hasRole } = useAuth();
  const { show } = useToast();
  const isAdmin = hasRole(['super_admin']);

  const [sources, setSources] = useState<DataSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiGet<{ sources: DataSource[] }>('/api/data-sources');
      setSources(res.sources ?? []);
    } catch (err) {
      show(err instanceof ApiError ? err.message : 'Failed to load data sources', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [show]);

  useEffect(() => {
    if (isAdmin) load();
    else setLoading(false);
  }, [isAdmin, load]);

  const testSaved = async (s: DataSource) => {
    setBusyId(s.id);
    try {
      const res = await apiPost<TestResult>(`/api/data-sources/${s.id}/test`);
      show(res.message, { variant: res.ok ? 'success' : 'error', title: res.ok ? 'Connection OK' : 'Connection failed' });
      await load();
    } catch (err) {
      show(err instanceof ApiError ? err.message : 'Test failed', { variant: 'error' });
    } finally {
      setBusyId(null);
    }
  };

  const activate = async (s: DataSource) => {
    if (s.is_active) return;
    setBusyId(s.id);
    try {
      await apiPost(`/api/data-sources/${s.id}/activate`);
      // The dashboard reads from the active source — drop cached responses so
      // every page re-fetches against the new source immediately.
      clearApiCache();
      show(`"${s.name}" is now the active data source. The dashboard will reflect it.`, {
        variant: 'success', title: 'Source activated',
      });
      await load();
    } catch (err) {
      show(err instanceof ApiError ? err.message : 'Activation failed', { variant: 'error' });
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (s: DataSource) => {
    if (!window.confirm(`Delete data source "${s.name}"? This cannot be undone.`)) return;
    setBusyId(s.id);
    try {
      await apiDelete(`/api/data-sources/${s.id}`);
      show(`Deleted "${s.name}"`, { variant: 'success' });
      await load();
    } catch (err) {
      show(err instanceof ApiError ? err.message : 'Delete failed', { variant: 'error' });
    } finally {
      setBusyId(null);
    }
  };

  // ── Access gate ─────────────────────────────────────────────────────────
  if (!isAdmin) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-5xl mx-auto">
          <PageHeader title="Data Sources" description="Connect and manage analytics data sources" icon={<Database className="w-5 h-5" />} />
          <Card padding="lg">
            <EmptyState
              icon={<Lock className="w-6 h-6" />}
              title="Super-admin access required"
              description="Connecting external databases is restricted to super-admin accounts."
            />
          </Card>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-5xl mx-auto">
        <PageHeader
          title="Data Sources"
          description="Connect a client's database and the whole dashboard reads from it. The built-in demo stays available to switch back to."
          icon={<Database className="w-5 h-5" />}
          actions={
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
              <Button size="sm" onClick={() => setShowAdd(true)}>
                <Plus className="w-4 h-4" />
                Connect a database
              </Button>
            </div>
          }
        />

        {loading ? (
          <Card padding="lg">
            <div className="flex items-center justify-center py-12 text-ink-muted gap-2">
              <RefreshCw className="w-4 h-4 animate-spin" /> Loading sources…
            </div>
          </Card>
        ) : sources.length === 0 ? (
          <Card padding="lg">
            <EmptyState
              icon={<Server className="w-6 h-6" />}
              title="No data sources yet"
              description="Connect a Postgres database to power the dashboard with your own data."
              action={<Button size="sm" onClick={() => setShowAdd(true)}><Plus className="w-4 h-4" />Connect a database</Button>}
            />
          </Card>
        ) : (
          <div className="space-y-3">
            {sources.map((s) => (
              <SourceCard
                key={s.id}
                source={s}
                busy={busyId === s.id}
                onTest={() => testSaved(s)}
                onActivate={() => activate(s)}
                onDelete={() => remove(s)}
              />
            ))}
          </div>
        )}
      </div>

      <AddSourceModal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        onCreated={async () => { setShowAdd(false); await load(); }}
      />
    </main>
  );
}

// ---------------------------------------------------------------------------
// Source card
// ---------------------------------------------------------------------------

function StatusBadge({ source }: { source: DataSource }) {
  if (source.type === 'builtin') return <Badge variant="violet">Built-in</Badge>;
  if (source.status === 'ok') return <Badge variant="success"><CheckCircle2 className="w-3 h-3" />Tested OK</Badge>;
  if (source.status === 'error') return <Badge variant="danger"><AlertCircle className="w-3 h-3" />Test failed</Badge>;
  return <Badge variant="neutral">Untested</Badge>;
}

function SourceCard({
  source, busy, onTest, onActivate, onDelete,
}: {
  source: DataSource;
  busy: boolean;
  onTest: () => void;
  onActivate: () => void;
  onDelete: () => void;
}) {
  const isBuiltin = source.type === 'builtin';
  const mapped = REQUIRED_FIELDS
    .map((f) => source.mapping?.[f])
    .filter(Boolean).length;

  return (
    <Card padding="lg" className={source.is_active ? 'ring-2 ring-coral-300' : ''}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-semibold text-ink truncate">{source.name}</h3>
            {source.is_active ? (
              <Badge variant="coral"><ShieldCheck className="w-3 h-3" />Active</Badge>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs text-ink-muted">
                <Circle className="w-2.5 h-2.5" />Inactive
              </span>
            )}
            <StatusBadge source={source} />
            <Badge variant="neutral">{source.type}</Badge>
          </div>

          <div className="mt-2 text-sm text-ink-muted space-y-1">
            {isBuiltin ? (
              <p>Synthetic demo dataset (the default). Always available as a fallback.</p>
            ) : (
              <>
                <p>
                  Table <code className="text-ink">{source.mapping?.table || '—'}</code> ·{' '}
                  {mapped}/{REQUIRED_FIELDS.length} required fields mapped
                  {source.mapping?.price ? ' · revenue (price mapped)' : ' · units only'}
                </p>
                {source.last_error && (
                  <p className="text-rose-600">{source.last_error}</p>
                )}
                {source.last_tested_at && !source.last_error && (
                  <p className="text-ink-muted">Last tested {new Date(source.last_tested_at).toLocaleString()}</p>
                )}
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {!isBuiltin && (
            <Button variant="secondary" size="sm" onClick={onTest} loading={busy} disabled={busy}>
              Test
            </Button>
          )}
          <Button
            size="sm"
            onClick={onActivate}
            disabled={busy || source.is_active}
            variant={source.is_active ? 'ghost' : 'primary'}
          >
            <Power className="w-4 h-4" />
            {source.is_active ? 'Active' : 'Activate'}
          </Button>
          {!isBuiltin && !source.is_active && (
            <Button variant="ghost" size="sm" onClick={onDelete} disabled={busy} className="text-rose-600 hover:bg-rose-50">
              <Trash2 className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Add-source modal (connect + map + test before saving)
// ---------------------------------------------------------------------------

const EMPTY_MAPPING: Record<MappingField | 'table', string> = {
  table: '', date: '', store: '', item: '', quantity: '', category: '', price: '',
};

function AddSourceModal({
  open, onClose, onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { show } = useToast();
  const [name, setName] = useState('');
  const [type, setType] = useState<'postgres'>('postgres');
  const [connection, setConnection] = useState('');
  const [map, setMap] = useState({ ...EMPTY_MAPPING });
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState<TestResult | null>(null);

  const reset = () => {
    setName(''); setConnection(''); setMap({ ...EMPTY_MAPPING }); setTest(null);
  };

  const close = () => { reset(); onClose(); };

  const setField = (field: MappingField | 'table', value: string) => {
    setMap((m) => ({ ...m, [field]: value }));
    setTest(null); // mapping changed — previous test result no longer applies
  };

  const buildMapping = () => {
    const out: Record<string, string> = {};
    (['table', ...REQUIRED_FIELDS, ...OPTIONAL_FIELDS] as const).forEach((f) => {
      const v = map[f].trim();
      if (v) out[f] = v;
    });
    return out;
  };

  const missingRequired = REQUIRED_FIELDS.filter((f) => !map[f].trim());
  const canTest = connection.trim().length > 0;
  const canSave = name.trim() && connection.trim() && map.table.trim() && missingRequired.length === 0;

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      const res = await apiPost<TestResult>('/api/data-sources/test', {
        type, connection: connection.trim(), mapping: buildMapping(),
      });
      setTest(res);
    } catch (err) {
      setTest({ ok: false, message: err instanceof ApiError ? err.message : 'Test failed' });
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiPost('/api/data-sources', {
        name: name.trim(), type, connection: connection.trim(), mapping: buildMapping(),
      });
      show(`Saved "${name.trim()}". Activate it to switch the dashboard.`, { variant: 'success' });
      reset();
      onCreated();
    } catch (err) {
      show(err instanceof ApiError ? err.message : 'Could not save source', { variant: 'error' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={close} title="Connect a database" size="lg">
      <div className="space-y-5 max-h-[70vh] overflow-y-auto pr-1">
        <Input
          label="Display name"
          placeholder="e.g. Acme Retail — Production"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        <Select label="Database type" value={type} onChange={(e) => setType(e.target.value as 'postgres')}>
          <option value="postgres">PostgreSQL</option>
          <option value="mongo" disabled>MongoDB (coming soon)</option>
        </Select>

        <Input
          label="Connection string"
          placeholder="postgresql://user:password@host:5432/dbname"
          value={connection}
          onChange={(e) => { setConnection(e.target.value); setTest(null); }}
          autoComplete="off"
          spellCheck={false}
        />
        <p className="-mt-3 text-xs text-ink-muted">
          Stored encrypted at rest. Use a read-only user scoped to the analytics table.
        </p>

        <div className="border-t border-coral-100 pt-4">
          <h4 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-1">Column mapping</h4>
          <p className="text-xs text-ink-muted mb-4">
            Tell the dashboard which columns hold each value. <code>category</code> and <code>price</code> are optional.
          </p>

          <Input
            label="Table (or schema.table)"
            placeholder="e.g. public.sales"
            value={map.table}
            onChange={(e) => setField('table', e.target.value)}
            className="mb-4"
          />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {REQUIRED_FIELDS.map((f) => (
              <div key={f}>
                <Input
                  label={`${f[0].toUpperCase()}${f.slice(1)} *`}
                  placeholder={FIELD_HINTS[f]}
                  value={map[f]}
                  onChange={(e) => setField(f, e.target.value)}
                />
              </div>
            ))}
            {OPTIONAL_FIELDS.map((f) => (
              <div key={f}>
                <Input
                  label={`${f[0].toUpperCase()}${f.slice(1)}`}
                  placeholder={FIELD_HINTS[f]}
                  value={map[f]}
                  onChange={(e) => setField(f, e.target.value)}
                />
              </div>
            ))}
          </div>
        </div>

        {test && (
          <div
            className={`rounded-xl border p-3 flex items-start gap-2 text-sm ${
              test.ok
                ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                : 'bg-rose-50 border-rose-200 text-rose-700'
            }`}
          >
            {test.ok ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /> : <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />}
            <span>{test.message}</span>
          </div>
        )}

        {missingRequired.length > 0 && (
          <p className="text-xs text-amber-600">
            Map all required fields to save: {missingRequired.join(', ')}.
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 mt-5 pt-4 border-t border-coral-100">
        <Button variant="ghost" size="sm" onClick={close}>Cancel</Button>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={runTest} loading={testing} disabled={!canTest || testing}>
            Test connection
          </Button>
          <Button size="sm" onClick={save} loading={saving} disabled={!canSave || saving}>
            Save source
          </Button>
        </div>
      </div>
    </Modal>
  );
}
