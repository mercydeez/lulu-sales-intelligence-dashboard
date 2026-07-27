'use client';

import { useState } from 'react';
import { ShieldCheck, ShieldOff, KeyRound, Loader2, Copy, Check } from 'lucide-react';
import { Card, Badge, Button } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';

type Stage = 'idle' | 'enrolling' | 'disabling';

/** 2-step verification (TOTP) enrollment + management for the signed-in user. */
export default function TwoFactorSettings() {
  const { user, authFetch } = useAuth();
  // Optimistic local view of the enabled state (server is source of truth on next login).
  const [enabled, setEnabled] = useState<boolean>(Boolean((user as { two_factor_enabled?: boolean })?.two_factor_enabled));
  const [stage, setStage] = useState<Stage>('idle');
  const [secret, setSecret] = useState('');
  const [otpauth, setOtpauth] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [backupCodes, setBackupCodes] = useState<string[]>([]);

  const startSetup = async () => {
    setError(''); setBusy(true);
    try {
      const res = await authFetch('/api/auth/2fa/setup', { method: 'POST' });
      if (!res.ok) throw new Error('Could not start setup');
      const data = await res.json();
      setSecret(data.secret); setOtpauth(data.otpauth_uri); setStage('enrolling');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Setup failed');
    } finally { setBusy(false); }
  };

  const confirmEnable = async () => {
    setError(''); setBusy(true);
    try {
      const res = await authFetch('/api/auth/2fa/enable', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code.replace(/\s/g, '') }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Invalid code');
      setEnabled(true); setStage('idle'); setCode(''); setSecret('');
      setBackupCodes(Array.isArray(data.backup_codes) ? data.backup_codes : []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not enable');
    } finally { setBusy(false); }
  };

  const confirmDisable = async () => {
    setError(''); setBusy(true);
    try {
      const res = await authFetch('/api/auth/2fa/disable', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code.replace(/\s/g, '') }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Invalid code');
      setEnabled(false); setStage('idle'); setCode('');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not disable');
    } finally { setBusy(false); }
  };

  const copySecret = () => {
    navigator.clipboard?.writeText(secret).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <Card padding="lg" className="mt-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Two-step verification</h3>
          <Badge variant={enabled ? 'success' : 'neutral'} size="sm">{enabled ? 'On' : 'Off'}</Badge>
        </div>
        {enabled
          ? <ShieldCheck className="w-5 h-5 text-teal-600" />
          : <ShieldOff className="w-5 h-5 text-ink-muted" />}
      </div>

      <p className="text-sm text-ink-soft mb-4">
        Add a second factor with an authenticator app (Google Authenticator, Authy, 1Password).
        After enabling, you&apos;ll enter a 6-digit code each time you sign in.
      </p>

      {error && <div className="mb-3 text-sm text-rose-700 bg-rose-50 rounded-lg px-3 py-2">{error}</div>}

      {backupCodes.length > 0 && (
        <div className="mb-4 rounded-xl bg-amber-50 border border-amber-200 p-4">
          <p className="text-sm font-semibold text-amber-800 mb-1">Save your recovery codes</p>
          <p className="text-xs text-amber-700 mb-3">
            Each works once if you lose your authenticator. Store them somewhere safe — they won&apos;t be shown again.
          </p>
          <div className="grid grid-cols-2 gap-2 font-mono text-sm">
            {backupCodes.map((c) => (
              <code key={c} className="px-2 py-1 rounded bg-surface border border-amber-200 text-ink">{c}</code>
            ))}
          </div>
          <button onClick={() => setBackupCodes([])} className="mt-3 text-xs font-medium text-amber-800 underline">
            I&apos;ve saved them
          </button>
        </div>
      )}

      {stage === 'idle' && !enabled && (
        <Button variant="primary" size="sm" onClick={startSetup} disabled={busy}>
          {busy ? <Loader2 className="w-4 h-4 me-1.5 animate-spin" /> : <KeyRound className="w-4 h-4 me-1.5" />}
          Enable 2-step verification
        </Button>
      )}

      {stage === 'idle' && enabled && (
        <div className="space-y-3">
          <input
            value={code} inputMode="numeric"
            onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, '').slice(0, 7))}
            placeholder="Current 6-digit code"
            className="w-full max-w-xs px-3 py-2 rounded-lg border border-line tracking-widest focus:outline-none focus:ring-2 focus:ring-rose-400/30"
          />
          <Button variant="secondary" size="sm" onClick={confirmDisable} disabled={busy}>
            {busy ? <Loader2 className="w-4 h-4 me-1.5 animate-spin" /> : <ShieldOff className="w-4 h-4 me-1.5" />}
            Disable 2-step verification
          </Button>
        </div>
      )}

      {stage === 'enrolling' && (
        <div className="space-y-4">
          <div className="rounded-xl bg-surface-2 p-4">
            <p className="text-sm text-ink-soft mb-2">
              1. In your authenticator app, add an account and enter this key (or scan the otpauth link):
            </p>
            <div className="flex items-center gap-2">
              <code className="px-3 py-1.5 rounded-lg bg-surface border border-line text-ink font-mono text-sm break-all">{secret}</code>
              <button onClick={copySecret} className="p-2 rounded-lg hover:bg-surface text-ink-muted" title="Copy key">
                {copied ? <Check className="w-4 h-4 text-teal-600" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
            <p className="text-[11px] text-ink-muted mt-2 break-all font-mono">{otpauth}</p>
          </div>
          <div>
            <p className="text-sm text-ink-soft mb-2">2. Enter the 6-digit code your app shows:</p>
            <input
              value={code} inputMode="numeric" autoFocus
              onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, '').slice(0, 7))}
              placeholder="123456"
              className="w-full max-w-xs px-3 py-2 rounded-lg border border-line tracking-widest text-lg focus:outline-none focus:ring-2 focus:ring-teal-400/30"
            />
          </div>
          <div className="flex gap-2">
            <Button variant="primary" size="sm" onClick={confirmEnable} disabled={busy}>
              {busy ? <Loader2 className="w-4 h-4 me-1.5 animate-spin" /> : <ShieldCheck className="w-4 h-4 me-1.5" />}
              Confirm &amp; enable
            </Button>
            <Button variant="ghost" size="sm" onClick={() => { setStage('idle'); setCode(''); setError(''); }}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
