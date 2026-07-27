'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { Compass, ArrowLeft } from 'lucide-react';
import { PRODUCT_NAME } from '@/lib/brand';

const EASE = [0.22, 1, 0.36, 1] as const;

export default function NotFound() {
  return (
    <main className="min-h-screen flex items-center justify-center hero-mesh px-4 text-center">
      <motion.div
        className="w-full max-w-md glass-strong rounded-3xl shadow-elevated p-10"
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: EASE }}
      >
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl sunset-gradient text-white shadow-sunset mb-6">
          <Compass className="w-8 h-8" />
        </div>
        <p className="text-5xl font-bold text-ink tabular-nums">404</p>
        <h1 className="mt-2 text-lg font-semibold text-ink">Page not found</h1>
        <p className="mt-1 text-sm text-ink-muted">
          The page you’re looking for doesn’t exist or may have moved.
        </p>
        <Link
          href="/"
          className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 rounded-2xl btn-sunset text-white font-semibold text-sm active:scale-[0.97] transition-transform"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to dashboard
        </Link>
        <p className="mt-6 text-xs text-ink-muted">{PRODUCT_NAME}</p>
      </motion.div>
    </main>
  );
}
