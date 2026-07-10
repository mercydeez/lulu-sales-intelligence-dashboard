'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import {
  Card, PageHeader, Button, Input, Select, Stagger, RevealItem,
  SkeletonCard, ErrorState, useToast, NoPermissionState,
} from '@/components/ui';
import { apiGet, apiPut, ApiError } from '@/lib/apiClient';
import { Building2, ShieldAlert } from 'lucide-react';

// Keep these labels in sync with backend EMIRATES (services/uae_profile.py) and
// the DB CHECK constraint (migration 041).
const EMIRATES: { value: string; label: string }[] = [
  { value: 'abu_dhabi', label: 'Abu Dhabi' },
  { value: 'dubai', label: 'Dubai' },
  { value: 'sharjah', label: 'Sharjah' },
  { value: 'ajman', label: 'Ajman' },
  { value: 'umm_al_quwain', label: 'Umm Al Quwain' },
  { value: 'ras_al_khaimah', label: 'Ras Al Khaimah' },
  { value: 'fujairah', label: 'Fujairah' },
];
const PROCUREMENT = [
  { value: 'self_serve', label: 'Self-serve' },
  { value: 'manual_invoice', label: 'Manual invoice' },
  { value: 'purchase_order', label: 'Purchase order' },
];

type Profile = Record<string, string | number | boolean | null>;

export default function CompanyProfilePage() {
  const { user } = useAuth();
  const { t } = useLanguage();
  const { show } = useToast();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const isAdmin = ['super_admin', 'admin'].includes(user?.role ?? '');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet<{ profile: Profile }>('/api/tenants/billing-profile');
      setProfile(res.profile);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load company profile');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAdmin) load();
    else setLoading(false);
  }, [isAdmin, load]);

  const set = (key: string, value: string | boolean) =>
    setProfile((p) => ({ ...(p ?? {}), [key]: value }));

  const save = async () => {
    if (!profile) return;
    setSaving(true);
    try {
      // Send only the editable, user-facing fields (drop server-managed columns).
      const SERVER_MANAGED = new Set(['tenant_id', 'created_at', 'updated_at']);
      const payload: Profile = {};
      Object.entries(profile).forEach(([k, val]) => {
        if (SERVER_MANAGED.has(k)) return;
        if (k === 'store_count' || k === 'sku_count') {
          payload[k] = val === '' || val == null ? null : Number(val);
        } else {
          payload[k] = val;
        }
      });
      const res = await apiPut<{ profile: Profile }>('/api/tenants/billing-profile', payload);
      setProfile(res.profile);
      show('Company profile saved', { variant: 'success' });
    } catch (e) {
      show(e instanceof ApiError ? e.message : 'Unexpected error', {
        variant: 'error',
        title: 'Could not save',
      });
    } finally {
      setSaving(false);
    }
  };

  if (!isAdmin) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-3xl mx-auto">
          <Card padding="none">
            <NoPermissionState
              title="Admin access required"
              description="Only a tenant administrator can manage the company legal & billing profile."
            />
          </Card>
        </div>
      </main>
    );
  }

  const v = (k: string) => (profile?.[k] ?? '') as string;

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-3xl mx-auto">
        <PageHeader
          title={t('settings.company.title')}
          description={t('settings.company.description')}
          icon={<Building2 className="w-5 h-5" />}
        />

        {loading ? (
          <div className="space-y-4"><SkeletonCard /><SkeletonCard /></div>
        ) : error ? (
          <ErrorState title="Couldn't load profile" description={error} onRetry={load} />
        ) : (
          <Stagger className="space-y-6">
            {/* Legal identity */}
            <RevealItem><Card padding="lg">
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Legal identity</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Input label="Legal company name" value={v('legal_name')} onChange={(e) => set('legal_name', e.target.value)} />
                <Input label="Legal name (Arabic)" dir="rtl" value={v('legal_name_ar')} onChange={(e) => set('legal_name_ar', e.target.value)} />
                <Input label="Trading name" value={v('trading_name')} onChange={(e) => set('trading_name', e.target.value)} />
                <Input label="TRN (15 digits)" inputMode="numeric" value={v('trn')} onChange={(e) => set('trn', e.target.value)} />
                <Input label="Trade licence no." value={v('trade_license_no')} onChange={(e) => set('trade_license_no', e.target.value)} />
              </div>
            </Card></RevealItem>

            {/* Location & VAT */}
            <RevealItem><Card padding="lg">
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Location &amp; VAT</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Select label="Emirate" value={v('emirate')} onChange={(e) => set('emirate', e.target.value)}>
                  <option value="">—</option>
                  {EMIRATES.map((e) => <option key={e.value} value={e.value}>{e.label}</option>)}
                </Select>
                <Select label="Jurisdiction" value={v('jurisdiction')} onChange={(e) => set('jurisdiction', e.target.value)}>
                  <option value="">—</option>
                  <option value="mainland">Mainland</option>
                  <option value="free_zone">Free zone</option>
                </Select>
                <Input label="Free zone name" value={v('free_zone_name')} onChange={(e) => set('free_zone_name', e.target.value)} />
                <Select label="VAT registered" value={String(profile?.vat_registered ?? true)} onChange={(e) => set('vat_registered', e.target.value === 'true')}>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </Select>
                <Input label="Registered address" value={v('registered_address')} onChange={(e) => set('registered_address', e.target.value)} />
                <Input label="Billing address" value={v('billing_address')} onChange={(e) => set('billing_address', e.target.value)} />
              </div>
            </Card></RevealItem>

            {/* Locale defaults */}
            <RevealItem><Card padding="lg">
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Locale defaults</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <Input label="Currency" value={v('currency') || 'AED'} onChange={(e) => set('currency', e.target.value.toUpperCase())} />
                <Input label="Timezone" value={v('timezone') || 'Asia/Dubai'} onChange={(e) => set('timezone', e.target.value)} />
                <Select label="Preferred language" value={v('preferred_language') || 'en'} onChange={(e) => set('preferred_language', e.target.value)}>
                  <option value="en">English</option>
                  <option value="ar">Arabic</option>
                </Select>
              </div>
            </Card></RevealItem>

            {/* Commercial profile */}
            <RevealItem><Card padding="lg">
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Commercial profile</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Input label="Industry vertical" value={v('industry_vertical')} onChange={(e) => set('industry_vertical', e.target.value)} />
                <Select label="Procurement type" value={v('procurement_type')} onChange={(e) => set('procurement_type', e.target.value)}>
                  <option value="">—</option>
                  {PROCUREMENT.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                </Select>
                <Input label="Store count" inputMode="numeric" value={v('store_count')} onChange={(e) => set('store_count', e.target.value)} />
                <Input label="SKU count" inputMode="numeric" value={v('sku_count')} onChange={(e) => set('sku_count', e.target.value)} />
              </div>
            </Card></RevealItem>

            {/* Contacts */}
            <RevealItem><Card padding="lg">
              <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-4">Contacts</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <Input label="Billing contact" value={v('billing_contact_name')} onChange={(e) => set('billing_contact_name', e.target.value)} />
                <Input label="Billing email" type="email" value={v('billing_contact_email')} onChange={(e) => set('billing_contact_email', e.target.value)} />
                <Input label="Billing phone" value={v('billing_contact_phone')} onChange={(e) => set('billing_contact_phone', e.target.value)} />
                <Input label="Finance contact" value={v('finance_contact_name')} onChange={(e) => set('finance_contact_name', e.target.value)} />
                <Input label="Finance email" type="email" value={v('finance_contact_email')} onChange={(e) => set('finance_contact_email', e.target.value)} />
                <Input label="Finance phone" value={v('finance_contact_phone')} onChange={(e) => set('finance_contact_phone', e.target.value)} />
              </div>
            </Card></RevealItem>

            <RevealItem>
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <p className="text-xs text-ink-muted max-w-md">
                  Draft — VAT/TRN/trade-licence fields are for invoicing readiness and require review
                  by a qualified UAE legal/tax professional before production use.
                </p>
                <Button onClick={save} disabled={saving}>
                  {saving ? 'Saving…' : 'Save profile'}
                </Button>
              </div>
            </RevealItem>
          </Stagger>
        )}
      </div>
    </main>
  );
}
