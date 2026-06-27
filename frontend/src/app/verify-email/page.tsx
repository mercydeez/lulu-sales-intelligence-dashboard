'use client';

import { Suspense, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { ShieldCheck, AlertCircle, Loader2 } from 'lucide-react';
import { PRODUCT_NAME } from '@/lib/brand';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function Verifier() {
  const token = useSearchParams().get('token') || '';
  const [state, setState] = useState<'working' | 'ok' | 'error'>('working');
  const [msg, setMsg] = useState('Verifying your email…');

  useEffect(() => {
    if (!token) { setState('error'); setMsg('Invalid verification link.'); return; }
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/auth/verify-email`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Verification failed');
        setState('ok'); setMsg('Your email is verified. You’re all set!');
      } catch (e: unknown) {
        setState('error'); setMsg(e instanceof Error ? e.message : 'Verification failed');
      }
    })();
  }, [token]);

  return (
    <div className="text-center space-y-4">
      {state === 'working' && <Loader2 className="w-12 h-12 text-teal-500 mx-auto animate-spin" />}
      {state === 'ok' && <ShieldCheck className="w-12 h-12 text-teal-500 mx-auto" />}
      {state === 'error' && <AlertCircle className="w-12 h-12 text-rose-500 mx-auto" />}
      <p className="text-ink font-semibold">{msg}</p>
      {state !== 'working' && (
        <Link href="/" className="inline-block text-sm font-medium text-violet-600 hover:text-teal-600">
          Go to dashboard →
        </Link>
      )}
    </div>
  );
}

export default function VerifyEmailPage() {
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
          <Verifier />
        </Suspense>
      </motion.div>
    </div>
  );
}
