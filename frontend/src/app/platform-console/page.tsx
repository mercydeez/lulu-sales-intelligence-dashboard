'use client';

/**
 * Platform Console — Customize (internal, platform developers only).
 *
 * Per-tenant bespoke configuration: every knob in the customization catalog,
 * grouped by category, with honest labelling of what is actually enforced.
 * Gated on `user.is_platform_developer` (the platform-operator boundary) —
 * NOT on super_admin, because tenant owners are super_admins too.
 *
 * The pill subnav below is deliberately replicated inline on each
 * /platform-console/* page (no shared component) so the three console pages
 * can be built in parallel without a merge-conflict hub.
 */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { SlidersHorizontal } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import {
  PageHeader, Card, Select, Input, Button, Badge, EmptyState, ErrorState,
  SkeletonCard, NoPermissionState, useToast,
} from '@/components/ui';

// ── Catalog contract (backend: /api/admin/dev/customizations/*) ────────────

type CustomizationCategory = 'modules' | 'assistant' | 'interface' | 'integrations' | 'limits';
type CustomizationType = 'bool' | 'enum' | 'int';
type CustomizationValue = boolean | string | number;
type EffectiveSource = 'default' | 'plan' | 'override';

interface CatalogEntry {
  key: string;
  label: string;
  description: string;
  category: CustomizationCategory;
  type: CustomizationType;
  default: CustomizationValue;
  options?: string[];
  min?: number;
  max?: number;
  plan_min?: string;
  enforced_by: string;
}

interface TenantCustomizations {
  tenant_id: number;
  tenant_name: string;
  plan: string;
  effective: Record<string, { value: CustomizationValue; source: EffectiveSource }>;
  overrides: Record<string, CustomizationValue>;
}

// Shape served by GET /api/tenants (see routes/tenants.py / admin tenants page).
interface Tenant { id: number; name: string; plan: string; status: string }

const CATEGORY_ORDER: { key: CustomizationCategory; label: string }[] = [
  { key: 'modules', label: 'Modules' },
  { key: 'assistant', label: 'Assistant' },
  { key: 'interface', label: 'Interface' },
  { key: 'integrations', label: 'Integrations' },
  { key: 'limits', label: 'Limits' },
];

const SOURCE_BADGE: Record<EffectiveSource, { variant: 'teal' | 'warning' | 'neutral'; label: string }> = {
  override: { variant: 'teal', label: 'bespoke' },
  plan: { variant: 'warning', label: 'plan-limited' },
  default: { variant: 'neutral', label: 'default' },
};

// ── Shared console subnav (replicated inline on every /platform-console page) ──

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

// ── Page ───────────────────────────────────────────────────────────────────

export default function PlatformConsolePage() {
  const { user, authFetch } = useAuth();
  const { show } = useToast();
  const isDev = Boolean(user?.is_platform_developer);

  // Tenant picker
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantsLoading, setTenantsLoading] = useState(true);
  const [tenantsError, setTenantsError] = useState(false);
  const [selectedId, setSelectedId] = useState('');

  // Catalog + per-tenant customization blob
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [blob, setBlob] = useState<TenantCustomizations | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(false);

  // Int controls: dirty drafts keyed by catalog key; which key is saving.
  const [draftInts, setDraftInts] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const loadTenants = useCallback(async () => {
    setTenantsLoading(true);
    setTenantsError(false);
    try {
      const res = await authFetch('/api/tenants');
      if (!res.ok) { setTenantsError(true); return; }
      setTenants((await res.json()).tenants ?? []);
    } catch {
      setTenantsError(true);
    } finally {
      setTenantsLoading(false);
    }
  }, [authFetch]);

  useEffect(() => { if (isDev) loadTenants(); }, [isDev, loadTenants]);

  const loadDetail = useCallback(async (tenantId: string) => {
    setDetailLoading(true);
    setDetailError(false);
    try {
      const [catRes, tenRes] = await Promise.all([
        authFetch('/api/admin/dev/customizations/catalog'),
        authFetch(`/api/admin/dev/customizations/${tenantId}`),
      ]);
      if (!catRes.ok || !tenRes.ok) { setDetailError(true); return; }
      setCatalog((await catRes.json()).catalog ?? []);
      setBlob(await tenRes.json());
    } catch {
      setDetailError(true);
    } finally {
      setDetailLoading(false);
    }
  }, [authFetch]);

  const selectTenant = (id: string) => {
    setSelectedId(id);
    setBlob(null);
    setDraftInts({});
    if (id) loadDetail(id);
  };

  /** PUT one knob; returns true on success (caller may clear its draft). */
  const putValue = async (key: string, value: CustomizationValue): Promise<boolean> => {
    setSavingKey(key);
    try {
      const res = await authFetch(`/api/admin/dev/customizations/${selectedId}/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      });
      if (res.ok) {
        show('Customization saved', { variant: 'success' });
        await loadDetail(selectedId);
        return true;
      }
      const err = await res.json().catch(() => ({}));
      show(typeof err.detail === 'string' ? err.detail : 'Change rejected', { variant: 'error' });
      return false;
    } catch {
      show('Change rejected — network error', { variant: 'error' });
      return false;
    } finally {
      setSavingKey(null);
    }
  };

  const revert = async (key: string) => {
    setSavingKey(key);
    try {
      const res = await authFetch(`/api/admin/dev/customizations/${selectedId}/${key}`, { method: 'DELETE' });
      if (res.ok) {
        show('Override reverted', { variant: 'success' });
        setDraftInts((d) => { const { [key]: _, ...rest } = d; return rest; });
        await loadDetail(selectedId);
      } else {
        const err = await res.json().catch(() => ({}));
        show(typeof err.detail === 'string' ? err.detail : 'Revert rejected', { variant: 'error' });
      }
    } catch {
      show('Revert rejected — network error', { variant: 'error' });
    } finally {
      setSavingKey(null);
    }
  };

  const saveInt = async (entry: CatalogEntry) => {
    const raw = draftInts[entry.key];
    const num = Number(raw);
    if (raw === undefined || raw.trim() === '' || !Number.isFinite(num)) {
      show('Enter a valid number', { variant: 'error' });
      return;
    }
    if (entry.min !== undefined && num < entry.min) {
      show(`Minimum is ${entry.min}`, { variant: 'error' });
      return;
    }
    if (entry.max !== undefined && num > entry.max) {
      show(`Maximum is ${entry.max}`, { variant: 'error' });
      return;
    }
    const ok = await putValue(entry.key, num);
    if (ok) setDraftInts((d) => { const { [entry.key]: _, ...rest } = d; return rest; });
  };

  // ── Gate (platform-operator boundary; NOT super_admin) ──────────────────
  if (!isDev) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-3xl mx-auto">
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

  const renderControl = (entry: CatalogEntry) => {
    const eff = blob?.effective[entry.key];
    const value = eff?.value ?? entry.default;
    const busy = savingKey === entry.key;

    if (entry.type === 'bool') {
      return (
        <Select
          aria-label={entry.label}
          value={value ? 'true' : 'false'}
          disabled={busy}
          onChange={(e) => putValue(entry.key, e.target.value === 'true')}
          className="py-2 text-sm"
        >
          <option value="true">Enabled</option>
          <option value="false">Disabled</option>
        </Select>
      );
    }

    if (entry.type === 'enum') {
      return (
        <Select
          aria-label={entry.label}
          value={String(value)}
          disabled={busy}
          onChange={(e) => putValue(entry.key, e.target.value)}
          className="py-2 text-sm"
        >
          {(entry.options ?? []).map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </Select>
      );
    }

    // int
    const draft = draftInts[entry.key];
    const dirty = draft !== undefined && draft !== String(value);
    return (
      <div className="flex items-center gap-2">
        <Input
          aria-label={entry.label}
          type="number"
          min={entry.min}
          max={entry.max}
          value={draft ?? String(value)}
          disabled={busy}
          onChange={(e) => setDraftInts((d) => ({ ...d, [entry.key]: e.target.value }))}
          className="py-2 text-sm"
        />
        {dirty && (
          <Button size="sm" loading={busy} onClick={() => saveInt(entry)}>Save</Button>
        )}
      </div>
    );
  };

  const renderRow = (entry: CatalogEntry) => {
    const eff = blob?.effective[entry.key];
    const source: EffectiveSource = eff?.source ?? 'default';
    const badge = SOURCE_BADGE[source];
    const overridden = source === 'override';
    return (
      <div
        key={entry.key}
        className="flex flex-col sm:flex-row sm:items-center gap-3 py-4 border-b border-line/60 first:pt-0 last:border-0 last:pb-0"
      >
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ink">{entry.label}</span>
            <Badge variant={badge.variant} size="sm">{badge.label}</Badge>
            {entry.enforced_by === 'planned' && (
              <Badge
                variant="neutral"
                size="sm"
                className="bg-ink/5 text-ink-muted"
                title="Honesty label: this toggle stores intent, but no runtime code consumes it yet."
              >
                not yet enforced
              </Badge>
            )}
          </div>
          <p className="text-xs text-ink-muted mt-1">{entry.description}</p>
          {entry.plan_min && (
            <p className="text-[11px] text-ink-muted mt-0.5">Plan minimum: {entry.plan_min}</p>
          )}
        </div>
        <div className="flex items-center gap-2 sm:w-64 shrink-0">
          <div className="flex-1">{renderControl(entry)}</div>
          {overridden && (
            <Button
              variant="ghost"
              size="sm"
              disabled={savingKey !== null}
              onClick={() => revert(entry.key)}
            >
              Revert
            </Button>
          )}
        </div>
      </div>
    );
  };

  const groupedCategories = CATEGORY_ORDER
    .map((cat) => ({ ...cat, entries: catalog.filter((e) => e.category === cat.key) }))
    .filter((cat) => cat.entries.length > 0);

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          eyebrow="Internal"
          title="Platform Console"
          description="Per-tenant bespoke configuration — every knob a client can ask for, honestly labelled."
          icon={<SlidersHorizontal className="w-5 h-5" />}
        />

        <ConsoleSubnav />

        {/* Tenant picker */}
        <Card padding="lg" className="mb-6">
          {tenantsError ? (
            <ErrorState
              title="Couldn't load tenants"
              description="The tenant list did not load — the console can't spec anything without it."
              onRetry={loadTenants}
            />
          ) : (
            <div className="max-w-md">
              <Select
                id="pc-tenant"
                label="Tenant"
                value={selectedId}
                disabled={tenantsLoading}
                onChange={(e) => selectTenant(e.target.value)}
              >
                <option value="">{tenantsLoading ? 'Loading tenants…' : 'Select a tenant…'}</option>
                {tenants.map((t) => (
                  <option key={t.id} value={String(t.id)}>{t.name} — {t.plan}</option>
                ))}
              </Select>
            </div>
          )}
        </Card>

        {/* Customization catalog for the selected tenant */}
        {!selectedId ? (
          <Card padding="none">
            <EmptyState
              title="Pick a tenant to spec"
              description="Choose a tenant above to view and tune its bespoke configuration."
            />
          </Card>
        ) : detailLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
        ) : detailError ? (
          <Card padding="none">
            <ErrorState
              title="Couldn't load customizations"
              description="The customization API didn't respond for this tenant. Try again."
              onRetry={() => loadDetail(selectedId)}
            />
          </Card>
        ) : blob ? (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">
                {blob.tenant_name}
              </h2>
              <Badge variant="violet" size="sm">{blob.plan}</Badge>
              <span className="text-xs text-ink-muted">
                {Object.keys(blob.overrides).length} bespoke override{Object.keys(blob.overrides).length === 1 ? '' : 's'}
              </span>
            </div>
            {groupedCategories.length === 0 ? (
              <Card padding="none">
                <EmptyState
                  title="No customization knobs"
                  description="The catalog is empty — nothing to spec for this tenant yet."
                />
              </Card>
            ) : (
              groupedCategories.map((cat) => (
                <Card key={cat.key} padding="lg">
                  <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-2">
                    {cat.label}
                  </h3>
                  <div>{cat.entries.map(renderRow)}</div>
                </Card>
              ))
            )}
          </div>
        ) : null}
      </div>
    </main>
  );
}
