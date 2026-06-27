'use client';

import { useEffect } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';
import Link from 'next/link';
import { PRODUCT_NAME } from '@/lib/brand';

const EASE = [0.22, 1, 0.36, 1] as const;

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface the error for diagnostics; the UI stays calm and actionable.
    console.error('Route error boundary caught:', error);
  }, [error]);

  return (
    <main className="min-h-screen flex items-center justify-center hero-mesh px-4 text-center">
      <motion.div
        className="w-full max-w-md glass-strong rounded-3xl shadow-elevated p-10"
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: EASE }}
      >
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-rose-100 text-rose-600 mb-6">
          <AlertTriangle className="w-8 h-8" />
        </div>
        <h1 className="text-lg font-semibold text-ink">Something went wrong</h1>
        <p className="mt-1 text-sm text-ink-muted">
          An unexpected error interrupted this page. You can retry, or head back to the dashboard.
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <button
            onClick={reset}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-2xl btn-sunset text-white font-semibold text-sm active:scale-[0.97] transition-transform"
          >
            <RefreshCw className="w-4 h-4" />
            Try again
          </button>
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-2xl bg-surface border border-line text-ink font-semibold text-sm hover:bg-surface-2 active:scale-[0.97] transition"
          >
            <Home className="w-4 h-4" />
            Dashboard
          </Link>
        </div>
        <p className="mt-6 text-xs text-ink-muted">{PRODUCT_NAME}</p>
      </motion.div>
    </main>
  );
}
