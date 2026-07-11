'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Activity, RefreshCw, ShieldAlert } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import {
  PageHeader, Card, Select, Button, Badge, Modal,
  SkeletonCard, ErrorState, NoPermissionState, useToast,
} from '@/components/ui';

// ---------------------------------------------------------------------------
// Types — GET /api/admin/dev/ops/status contract. Any section may instead be
// {"error": "<ClassName>"}; the page must render that inline, never crash.
// ---------------------------------------------------------------------------

interface SectionError { error: string }

interface ProviderStatus {
  implemented?: boolean;
  configured?: boolean;
  usable?: boolean;
  available?: boolean;
  note?: string;
  error?: string;
}

type ProviderSection = Record<string, ProviderStatus> | SectionError;

interface OpsStatus {
  payments?: ProviderSection;
  pos?: ProviderSection;
  einvoicing?: ProviderSection;
  quotas?: { enforcement_on?: boolean } | SectionError;
  security?: { warnings?: number; critical?: number } | SectionError;
  environment?: string;
  demo_mode?: boolean;
  worker?: Record<string, unknown> | SectionError;
  db?: boolean;
  redis?: boolean;
}

function isSectionError(section: unknown): section is SectionError {
  return (
    typeof section === 'object' && section !== null &&
    typeof (section as SectionError).error === 'string'
  );
}

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

const PROVIDER_NAMES: Record<string, string> = {
  telr: 'Telr',
  paytabs: 'PayTabs',
  square: 'Square',
  uae_fta: 'UAE FTA',
};

function providerLabel(key: string): string {
  if (PROVIDER_NAMES[key]) return PROVIDER_NAMES[key];
  return key
    .split('_')
    .map((w) => (w.length <= 3 ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(' ');
}

function ProviderBadge({ provider }: { provider: ProviderStatus }) {
  if (typeof provider.error === 'string') {
    return <Badge variant="warning">unavailable: {provider.error}</Badge>;
  }
  if (provider.usable || provider.available) {
    return <Badge variant="teal">usable</Badge>;
  }
  if (provider.implemented) {
    return <Badge variant="warning">needs credentials</Badge>;
  }
  // Honesty posture: an unbuilt integration is refused, not faked.
  return <Badge variant="neutral">not integrated — refused</Badge>;
}

function ProviderCard({ title, section }: { title: string; section?: ProviderSection }) {
  return (
    <Card padding="lg">
      <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-3">{title}</h3>
      {section === undefined ? (
        <p className="text-sm text-ink-muted">Not reported by the status endpoint.</p>
      ) : isSectionError(section) ? (
        <Badge variant="warning">unavailable: {section.error}</Badge>
      ) : Object.keys(section).length === 0 ? (
        <p className="text-sm text-ink-muted">No providers registered.</p>
      ) : (
        <ul>
          {Object.entries(section).map(([key, provider]) => (
            <li
              key={key}
              className="flex items-start justify-between gap-3 py-2.5 border-b border-line/60 last:border-0 last:pb-0 first:pt-0"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink">{providerLabel(key)}</p>
                {provider.note && <p className="text-xs text-ink-muted mt-0.5">{provider.note}</p>}
              </div>
              <div className="shrink-0"><ProviderBadge provider={provider} /></div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function HealthDot({ ok }: { ok: boolean | null }) {
  const color = ok === null ? 'bg-ink/20' : ok ? 'bg-teal-500' : 'bg-rose-500';
  return <span aria-hidden className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />;
}

function PlatformRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5 border-b border-line/60 last:border-0 last:pb-0 first:pt-0">
      <span className="text-sm text-ink-soft">{label}</span>
      <span className="flex items-center gap-2 text-sm text-ink">{children}</span>
    </div>
  );
}

const WORKER_OK_STATUSES = ['ok', 'alive', 'healthy', 'running', 'up'];
const WORKER_BAD_STATUSES = ['down', 'dead', 'stopped', 'stale', 'unhealthy'];

function describeWorker(worker?: Record<string, unknown> | SectionError): { ok: boolean | null; text: string } {
  if (worker === undefined) return { ok: null, text: 'not reported' };
  if (isSectionError(worker)) return { ok: false, text: `unavailable: ${worker.error}` };
  const aliveFlag = [worker.alive, worker.ok, worker.healthy, worker.running]
    .find((v): v is boolean => typeof v === 'boolean');
  const status = typeof worker.status === 'string' ? worker.status : undefined;
  const heartbeat =
    typeof worker.last_heartbeat === 'string' ? worker.last_heartbeat
    : typeof worker.heartbeat === 'string' ? worker.heartbeat
    : undefined;
  const ok =
    aliveFlag !== undefined ? aliveFlag
    : status !== undefined && WORKER_OK_STATUSES.includes(status.toLowerCase()) ? true
    : status !== undefined && WORKER_BAD_STATUSES.includes(status.toLowerCase()) ? false
    : null;
  const parts: string[] = [];
  parts.push(status ?? (aliveFlag !== undefined ? (aliveFlag ? 'alive' : 'down') : 'unknown'));
  if (heartbeat) parts.push(`last heartbeat ${heartbeat}`);
  return { ok, text: parts.join(' · ') };
}

// ---------------------------------------------------------------------------
// Inline subnav — deliberately self-contained (no sibling imports).
// ---------------------------------------------------------------------------

const SUBNAV = [
  { href: '/platform-console', label: 'Customize' },
  { href: '/platform-console/bespoke', label: 'Bespoke Atelier' },
  { href: '/platform-console/ops', label: 'Ops & Readiness' },
];

function ConsoleSubnav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Platform console sections" className="mb-6 flex flex-wrap gap-2">
      {SUBNAV.map(({ href, label }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? 'page' : undefined}
            className={`rounded-full border px-4 py-1.5 text-sm font-medium transition-colors ${
              active
                ? 'border-teal-400 bg-teal-50 text-teal-700 dark:bg-teal-500/10 dark:text-teal-300'
                : 'border-line text-ink-soft hover:bg-surface-2 hover:text-ink'
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const FLUSH_SCOPES = ['inventory', 'promotions', 'alerts', 'all'] as const;

export default function OpsReadinessPage() {
  const { user, authFetch } = useAuth();
  const { show } = useToast();
  const isDev = Boolean(user?.is_platform_developer);

  const [status, setStatus] = useState<OpsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const [resetOpen, setResetOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [flushScope, setFlushScope] = useState<string>('all');
  const [flushing, setFlushing] = useState(false);

  // Mirror modal state into a ref so the 30s interval can skip refreshes
  // while the confirm dialog is open without re-arming the timer.
  const modalOpenRef = useRef(false);
  modalOpenRef.current = resetOpen;

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await authFetch('/api/admin/dev/ops/status');
      if (!res.ok) throw new Error(`Status endpoint returned ${res.status}`);
      setStatus((await res.json()) as OpsStatus);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reach the status endpoint');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    if (isDev) void load();
    else setLoading(false);
  }, [isDev, load]);

  // Auto-refresh every 30s while mounted; paused while a modal is open.
  useEffect(() => {
    if (!isDev) return;
    const id = setInterval(() => {
      if (!modalOpenRef.current) void load(true);
    }, 30_000);
    return () => clearInterval(id);
  }, [isDev, load]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await load(true);
    } finally {
      setRefreshing(false);
    }
  };

  const runDemoReset = async () => {
    setResetting(true);
    try {
      const res = await authFetch('/api/admin/dev/ops/demo-reset', { method: 'POST' });
      if (res.ok) {
        const summary: Record<string, unknown> = await res.json().catch(() => ({}));
        const counts = Object.entries(summary)
          .filter(([, v]) => typeof v === 'number')
          .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v as number}`)
          .join(', ');
        show(counts ? `Demo tenant reset — ${counts}` : 'Demo tenant reset complete', { variant: 'success' });
        setResetOpen(false);
        void load(true);
      } else {
        const err = await res.json().catch(() => ({} as { detail?: string }));
        show(err.detail || 'Demo reset failed', { variant: 'error' });
      }
    } catch {
      show('Demo reset failed — could not reach the server', { variant: 'error' });
    } finally {
      setResetting(false);
    }
  };

  const runCacheFlush = async () => {
    setFlushing(true);
    try {
      const res = await authFetch('/api/admin/dev/ops/cache-flush', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: flushScope }),
      });
      if (res.ok) {
        const data: { flushed?: string[] } = await res.json().catch(() => ({}));
        const flushed = data.flushed ?? [];
        show(flushed.length ? `Flushed: ${flushed.join(', ')}` : 'Nothing to flush', { variant: 'success' });
      } else {
        const err = await res.json().catch(() => ({} as { detail?: string }));
        show(err.detail || 'Cache flush failed', { variant: 'error' });
      }
    } catch {
      show('Cache flush failed — could not reach the server', { variant: 'error' });
    } finally {
      setFlushing(false);
    }
  };

  if (!isDev) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-3xl mx-auto">
          <Card padding="none">
            <NoPermissionState
              title="Platform developers only"
              description="The Platform Console is an internal tool restricted to platform developers."
            />
          </Card>
        </div>
      </main>
    );
  }

  const quotas = status?.quotas;
  const security = status?.security;
  const worker = describeWorker(status?.worker);
  const criticalCount = !isSectionError(security) ? security?.critical ?? 0 : 0;

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          eyebrow="Internal"
          title="Ops & Readiness"
          description="Honest platform status — what's integrated, what's configured, what's refused."
          icon={<Activity className="w-5 h-5" />}
          actions={
            <Button variant="ghost" size="md" onClick={refresh} loading={refreshing}>
              <RefreshCw className="w-4 h-4" />
              Refresh
            </Button>
          }
        />

        <ConsoleSubnav />

        {loading && !status ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : !status && error ? (
          <Card padding="none">
            <ErrorState
              title="Ops status unavailable"
              description={error}
              onRetry={() => void load()}
            />
          </Card>
        ) : status ? (
          <>
            {error && (
              <p className="text-xs text-amber-600 dark:text-amber-400 mb-4" role="status">
                Showing last known status — latest refresh failed ({error}).
              </p>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <ProviderCard title="Payments" section={status.payments} />
              <ProviderCard title="POS" section={status.pos} />
              <ProviderCard title="E-invoicing" section={status.einvoicing} />

              <Card padding="lg">
                <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-3">Platform</h3>

                <PlatformRow label="Environment">
                  <span className="font-medium">{status.environment ?? 'unknown'}</span>
                  <Badge variant={status.demo_mode ? 'amber' : 'neutral'}>
                    {status.demo_mode ? 'demo mode' : 'demo mode off'}
                  </Badge>
                </PlatformRow>

                <PlatformRow label="Database">
                  <HealthDot ok={typeof status.db === 'boolean' ? status.db : null} />
                  {typeof status.db === 'boolean' ? (status.db ? 'connected' : 'down') : 'unknown'}
                </PlatformRow>

                <PlatformRow label="Redis">
                  <HealthDot ok={typeof status.redis === 'boolean' ? status.redis : null} />
                  {typeof status.redis === 'boolean' ? (status.redis ? 'connected' : 'down') : 'unknown'}
                </PlatformRow>

                <PlatformRow label="Worker heartbeat">
                  <HealthDot ok={worker.ok} />
                  {worker.text}
                </PlatformRow>

                <PlatformRow label="Quotas">
                  {quotas === undefined ? (
                    <span className="text-ink-muted">not reported</span>
                  ) : isSectionError(quotas) ? (
                    <Badge variant="warning">unavailable: {quotas.error}</Badge>
                  ) : (
                    <Badge variant={quotas.enforcement_on ? 'teal' : 'neutral'}>
                      {quotas.enforcement_on ? 'enforcing' : 'metering only'}
                    </Badge>
                  )}
                </PlatformRow>

                <PlatformRow label="Security findings">
                  {security === undefined ? (
                    <span className="text-ink-muted">not reported</span>
                  ) : isSectionError(security) ? (
                    <Badge variant="warning">unavailable: {security.error}</Badge>
                  ) : (
                    <>
                      <span>{security.warnings ?? 0} warnings</span>
                      <span className="text-ink-muted">·</span>
                      <span>{security.critical ?? 0} critical</span>
                      {criticalCount > 0 && (
                        <Badge variant="danger">
                          <ShieldAlert className="w-3 h-3" />
                          {criticalCount} critical
                        </Badge>
                      )}
                    </>
                  )}
                </PlatformRow>
              </Card>
            </div>

            <Card padding="lg" className="mt-6">
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Ops actions</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <p className="text-sm font-medium text-ink">Reset demo tenant</p>
                  <p className="text-xs text-ink-muted mt-1">
                    Wipes synthetic generator rows for the demo tenant. Requires confirmation.
                  </p>
                  <Button variant="danger" size="sm" className="mt-3" onClick={() => setResetOpen(true)}>
                    Reset demo tenant
                  </Button>
                </div>
                <div>
                  <p className="text-sm font-medium text-ink">Flush cache</p>
                  <p className="text-xs text-ink-muted mt-1">
                    Clears the selected Redis-backed cache scope.
                  </p>
                  <div className="mt-3 flex items-end gap-2">
                    <div className="flex-1 max-w-[14rem]">
                      <Select
                        id="cache-flush-scope"
                        label="Scope"
                        value={flushScope}
                        onChange={(e) => setFlushScope(e.target.value)}
                        className="!py-2 !rounded-md text-sm"
                      >
                        {FLUSH_SCOPES.map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </Select>
                    </div>
                    <Button variant="secondary" size="md" onClick={runCacheFlush} loading={flushing}>
                      Flush
                    </Button>
                  </div>
                </div>
              </div>
            </Card>
          </>
        ) : null}

        <Modal
          open={resetOpen}
          onClose={() => { if (!resetting) setResetOpen(false); }}
          title="Reset demo tenant?"
          size="sm"
        >
          <p className="text-sm text-ink-soft">
            This wipes synthetic rows for the demo tenant only — the service refuses any other tenant.
          </p>
          <p className="text-xs text-ink-muted mt-2">
            Only generator-written rows flagged as synthetic are deleted. Historical CSV data and real
            tenant data are untouched.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setResetOpen(false)} disabled={resetting}>
              Cancel
            </Button>
            <Button variant="danger" onClick={runDemoReset} loading={resetting}>
              Wipe synthetic data
            </Button>
          </div>
        </Modal>
      </div>
    </main>
  );
}
