'use client';

import { useCallback, useEffect, useState } from 'react';
import { Card, Button, useToast } from '@/components/ui';
import { apiGet, apiPut } from '@/lib/apiClient';
import { BellRing, Check } from 'lucide-react';

interface Prefs { muted_types: string[]; email_enabled: boolean; available_types: string[]; }

const TYPE_LABELS: Record<string, string> = {
  finding: 'Diagnostics findings',
  billing: 'Billing & invoices',
  lifecycle: 'Account status',
  export: 'Data exports',
  quota: 'Usage quota',
  system: 'System',
};

export default function NotificationPreferences() {
  const { show } = useToast();
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try { setPrefs(await apiGet<Prefs>('/api/notifications/preferences')); } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (!prefs) return null;

  const enabled = (t: string) => !prefs.muted_types.includes(t);
  const toggleType = (t: string) =>
    setPrefs((p) => p && ({
      ...p,
      muted_types: enabled(t) ? [...p.muted_types, t] : p.muted_types.filter((x) => x !== t),
    }));

  const save = async () => {
    setSaving(true);
    try {
      const res = await apiPut<Prefs>('/api/notifications/preferences', {
        muted_types: prefs.muted_types, email_enabled: prefs.email_enabled,
      });
      setPrefs(res);
      show('Notification preferences saved', { variant: 'success' });
    } catch {
      show('Could not save preferences', { variant: 'error' });
    } finally { setSaving(false); }
  };

  return (
    <Card padding="lg">
      <div className="flex items-center gap-2 mb-4">
        <BellRing className="w-4 h-4 text-teal-600" />
        <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Notifications</h3>
      </div>
      <div className="space-y-2">
        {prefs.available_types.map((t) => (
          <label key={t} className="flex items-center justify-between px-3 py-2.5 rounded-xl border border-line cursor-pointer hover:bg-surface-2/60">
            <span className="text-sm text-ink">{TYPE_LABELS[t] ?? t}</span>
            <span className={`w-5 h-5 rounded-md flex items-center justify-center border ${
              enabled(t) ? 'bg-teal-600 border-teal-600 text-white' : 'border-line text-transparent'}`}>
              <Check className="w-3.5 h-3.5" />
            </span>
            <input type="checkbox" className="sr-only" checked={enabled(t)} onChange={() => toggleType(t)} />
          </label>
        ))}
      </div>
      <label className="flex items-center justify-between px-3 py-2.5 mt-3 rounded-xl border border-line cursor-pointer hover:bg-surface-2/60">
        <span className="text-sm text-ink">Email notifications <span className="text-xs text-ink-muted">(stub — logged only)</span></span>
        <span className={`w-5 h-5 rounded-md flex items-center justify-center border ${
          prefs.email_enabled ? 'bg-teal-600 border-teal-600 text-white' : 'border-line text-transparent'}`}>
          <Check className="w-3.5 h-3.5" />
        </span>
        <input type="checkbox" className="sr-only" checked={prefs.email_enabled}
               onChange={(e) => setPrefs((p) => p && ({ ...p, email_enabled: e.target.checked }))} />
      </label>
      <div className="mt-4">
        <Button onClick={save} disabled={saving} size="sm">{saving ? 'Saving…' : 'Save preferences'}</Button>
      </div>
    </Card>
  );
}
