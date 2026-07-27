'use client';

import { Suspense, useState, FormEvent } from 'react';
import { motion } from 'framer-motion';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Lock, Loader2, ShieldCheck, AlertCircle, ArrowRight } from 'lucide-react';
import { PRODUCT_NAME } from '@/lib/brand';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function ResetForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get('token') || '';

  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (pw !== pw2) { setError('Passwords do not match'); return; }
    setBusy(true);
    try {
      const res = await fetch(`${API_URL}/api/auth/reset-password`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: pw }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not reset password');
      setDone(true);
      setTimeout(() => router.push('/login'), 2500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Reset failed');
    } finally { setBusy(false); }
  };

  if (!token) {
    return <p className="text-center text-ink-soft">Invalid reset link. <Link href="/login" className="text-violet-600 underline">Back to sign in</Link></p>;
  }
  if (done) {
    return (
      <div className="text-center space-y-3">
        <ShieldCheck className="w-12 h-12 text-teal-500 mx-auto" />
        <p className="text-ink font-semibold">Password reset successfully</p>
        <p className="text-sm text-ink-muted">Redirecting you to sign in…</p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <h1 className="text-2xl font-bold text-ink">Set a new password</h1>
      <p className="text-sm text-ink-muted">Choose a strong password (12+ chars, upper/lower/number/symbol).</p>
      {error && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 flex items-start gap-2">
          <AlertCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" /><p className="text-rose-700 text-sm">{error}</p>
        </div>
      )}
      {[['New password', pw, setPw], ['Confirm password', pw2, setPw2]].map(([label, val, set]) => (
        <div key={label as string} className="relative">
          <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none">
            <Lock className="w-5 h-5 text-ink-muted" />
          </div>
          <input
            type="password" value={val as string}
            onChange={(e) => (set as (s: string) => void)(e.target.value)}
            placeholder={label as string}
            className="w-full ps-12 pe-4 py-3.5 rounded-2xl bg-surface border border-line text-ink shadow-sm focus:outline-none focus:ring-4 focus:ring-teal-500/15 focus:border-teal-400"
            disabled={busy}
          />
        </div>
      ))}
      <button type="submit" disabled={busy} className="btn-sunset w-full py-3.5 rounded-2xl font-semibold flex items-center justify-center gap-2 disabled:opacity-60">
        {busy ? <><Loader2 className="w-5 h-5 animate-spin" /> Resetting…</> : <>Reset password <ArrowRight className="w-5 h-5" /></>}
      </button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="min-h-screen flex items-center justify-center hero-mesh px-4">
      <motion.div
        className="w-full max-w-md glass-strong rounded-3xl shadow-elevated p-8"
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      >
        <p className="text-xs font-medium text-ink-muted mb-6">{PRODUCT_NAME}</p>
        <Suspense fallback={<Loader2 className="w-6 h-6 animate-spin mx-auto" />}>
          <ResetForm />
        </Suspense>
      </motion.div>
    </div>
  );
}
