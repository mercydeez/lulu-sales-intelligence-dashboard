'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { PRODUCT_NAME } from '@/lib/brand';
import { track } from '@/lib/telemetry';
import {
  Eye, EyeOff, Lock, Mail, AlertCircle, Loader2,
  TrendingUp, ShieldCheck, Activity, Sparkles, ArrowRight, KeyRound,
} from 'lucide-react';
import { BrandIcon } from '@/components/branding/BrandIcon';

// Labels/features are translation keys (src/locales/auth.ts) — resolved with
// t() at render so the screen is fully EN/AR (E4-4 core screen).
const DEMO_ACCOUNTS = [
  { labelKey: 'auth.demo.superAdmin', email: 'atharva@retaildemo.app', grad: 'sunset-gradient' },
  { labelKey: 'auth.demo.regional', email: 'krishna@retaildemo.app', grad: 'grad-violet' },
  { labelKey: 'auth.demo.store', email: 'yash@retaildemo.app', grad: 'grad-amber' },
];

const FEATURES = [
  { icon: Activity, textKey: 'auth.feature.live' },
  { icon: TrendingUp, textKey: 'auth.feature.forecast' },
  { icon: ShieldCheck, textKey: 'auth.feature.rbac' },
];

const EASE = [0.22, 1, 0.36, 1] as const;

export default function LoginPage() {
  const router = useRouter();
  const { login, verifyTwoFactor, isLoading, error, clearError } = useAuth();
  const { t, toggleLang } = useLanguage();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [localError, setLocalError] = useState('');

  // 2-step verification: set once the password step returns a challenge.
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLocalError('');
    clearError();
    if (!email || !password) {
      setLocalError(t('auth.errBoth'));
      return;
    }
    const res = await login({ email, password, remember_me: rememberMe });
    if (res.ok) {
      track('login_succeeded');
      router.push('/');
    } else if (res.requires2fa && res.mfaToken) setMfaToken(res.mfaToken);
  };

  const handleVerify = async (e: FormEvent) => {
    e.preventDefault();
    setLocalError('');
    clearError();
    if (code.replace(/\s/g, '').length < 6) {
      setLocalError(t('auth.errCode'));
      return;
    }
    const ok = await verifyTwoFactor(mfaToken!, code.replace(/\s/g, ''));
    if (ok) {
      track('login_2fa_succeeded');
      router.push('/');
    }
  };

  const [forgotMsg, setForgotMsg] = useState('');
  const handleForgot = async () => {
    setForgotMsg(''); setLocalError('');
    if (!email) { setLocalError(t('auth.errForgotNeedsEmail')); return; }
    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      await fetch(`${API_URL}/api/auth/forgot-password`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
    } catch { /* ignore — generic message either way */ }
    setForgotMsg(t('auth.forgotSent'));
  };

  const fillDemo = (demoEmail: string) => {
    setEmail(demoEmail);
    setPassword('Demo@2026!');
    setLocalError('');
    clearError();
  };

  const displayError = error || localError;
  const inputCls =
    'w-full ps-12 pe-4 py-3.5 rounded-2xl bg-surface border border-line text-ink placeholder-ink-muted ' +
    'shadow-sm focus:outline-none focus:ring-4 focus:ring-teal-500/15 focus:border-teal-500 transition-all';

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      {/* ============================= BRAND PANEL ============================= */}
      <div className="relative hidden lg:flex flex-col justify-between overflow-hidden hero-mesh p-12 text-white">
        {/* Animated floating orbs for depth/motion */}
        {[
          { c: 'rgba(45,212,191,0.45)', s: 380, x: '-12%', y: '-10%', d: 0 },
          { c: 'rgba(139,92,246,0.40)', s: 320, x: '70%', y: '8%', d: 1.2 },
          { c: 'rgba(251,191,36,0.30)', s: 300, x: '30%', y: '62%', d: 2.4 },
        ].map((o, i) => (
          <motion.div
            key={i}
            aria-hidden
            className="pointer-events-none absolute rounded-full blur-3xl"
            style={{ width: o.s, height: o.s, left: o.x, top: o.y, background: o.c }}
            animate={{ y: [0, -22, 0], x: [0, 14, 0], scale: [1, 1.08, 1] }}
            transition={{ duration: 9 + i * 1.5, repeat: Infinity, ease: 'easeInOut', delay: o.d }}
          />
        ))}

        {/* Brand */}
        <motion.div
          initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="relative z-10 flex items-center gap-3"
        >
          <div className="flex items-center justify-center w-12 h-12 rounded-2xl bg-white/15 backdrop-blur-sm ring-1 ring-white/30">
            <BrandIcon size={24} decorative className="text-white" />
          </div>
          <span className="text-xl font-bold tracking-tight">{PRODUCT_NAME}</span>
        </motion.div>

        {/* Hero copy */}
        <div className="relative z-10 max-w-md">
          <motion.div
            initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, ease: EASE, delay: 0.05 }}
          >
            <div className="inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1 text-xs font-medium backdrop-blur-sm ring-1 ring-white/25 mb-5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white/80" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-white" />
              </span>
              {t('auth.badge')}
            </div>
            <h1 className="text-4xl font-bold leading-tight mb-4">
              {t('auth.heroTitle')}
            </h1>
            <p className="text-white/85 text-lg leading-relaxed">
              {t('auth.heroSub')}
            </p>
          </motion.div>

          {/* Feature pills (staggered) */}
          <motion.div
            className="mt-8 space-y-3"
            initial="hidden" animate="show"
            variants={{ show: { transition: { staggerChildren: 0.1, delayChildren: 0.25 } } }}
          >
            {FEATURES.map(({ icon: Icon, textKey }) => (
              <motion.div
                key={textKey}
                variants={{ hidden: { opacity: 0, x: -16 }, show: { opacity: 1, x: 0, transition: { ease: EASE } } }}
                className="flex items-center gap-3"
              >
                <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-white/15 backdrop-blur-sm ring-1 ring-white/25">
                  <Icon className="w-4 h-4" />
                </div>
                <span className="text-white/90 text-sm">{t(textKey)}</span>
              </motion.div>
            ))}
          </motion.div>
        </div>

        <div className="relative z-10 text-white/70 text-xs">
          {t('auth.footnote')}
        </div>
      </div>

      {/* ============================= FORM PANEL ============================= */}
      <div className="flex items-center justify-center p-6 sm:p-12">
        <motion.div
          initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: EASE }}
          className="w-full max-w-md"
        >
          {/* Language toggle — the Topbar only renders when authenticated, so
              the login screen needs its own EN/AR switch (E4-4). */}
          <div className="flex justify-end mb-4">
            <button
              type="button"
              onClick={toggleLang}
              className="px-3 py-1.5 rounded-lg border border-line text-xs font-semibold text-ink-muted hover:bg-surface-2 transition-colors"
            >
              {t('lang.toggle')}
            </button>
          </div>

          {/* Mobile brand */}
          <div className="lg:hidden text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl sunset-gradient mb-4 shadow-sunset">
              <BrandIcon size={32} decorative className="text-white" />
            </div>
            <h1 className="text-2xl font-bold text-ink">{PRODUCT_NAME}</h1>
            <p className="text-ink-muted text-sm">{t('auth.tagline')}</p>
          </div>

          <div className="mb-8">
            <h2 className="text-3xl font-bold text-ink mb-2">{t('auth.welcome')}</h2>
            <p className="text-ink-soft">{t('auth.signInSub')}</p>
          </div>

          {/* Error / info alerts */}
          {displayError && (
            <motion.div
              initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
              className="mb-6 p-4 rounded-2xl bg-coral-50 border border-coral-200 flex items-start gap-3"
            >
              <AlertCircle className="w-5 h-5 text-coral-600 flex-shrink-0 mt-0.5" />
              <p className="text-coral-700 text-sm">{displayError}</p>
            </motion.div>
          )}
          {forgotMsg && (
            <motion.div
              initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
              className="mb-6 p-4 rounded-2xl bg-teal-50 border border-teal-200 flex items-start gap-3"
            >
              <ShieldCheck className="w-5 h-5 text-teal-600 flex-shrink-0 mt-0.5" />
              <p className="text-teal-700 text-sm">{forgotMsg}</p>
            </motion.div>
          )}

          {mfaToken ? (
            <form onSubmit={handleVerify} className="space-y-5">
              <div className="flex items-center gap-3 p-4 rounded-2xl bg-teal-50 border border-teal-100">
                <ShieldCheck className="w-5 h-5 text-teal-600 shrink-0" />
                <p className="text-sm text-teal-800 dark:text-teal-200">
                  {t('auth.mfaNotice')}
                </p>
              </div>
              <div>
                <label htmlFor="code" className="block text-sm font-medium text-ink-soft mb-2">
                  {t('auth.authCode')}
                </label>
                <div className="relative group">
                  <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none">
                    <KeyRound className="w-5 h-5 text-ink-muted group-focus-within:text-teal-600 transition-colors" />
                  </div>
                  <input
                    id="code"
                    inputMode="numeric"
                    autoFocus
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, '').slice(0, 7))}
                    className={`${inputCls} tracking-[0.4em] text-lg`}
                    placeholder="123456"
                    autoComplete="one-time-code"
                    disabled={isLoading}
                  />
                </div>
              </div>
              <SubmitButton isLoading={isLoading} idle={t('auth.verify')} busy={t('auth.verifying')} />
              <button
                type="button"
                onClick={() => { setMfaToken(null); setCode(''); setLocalError(''); clearError(); }}
                className="w-full text-sm font-medium text-ink-muted hover:text-ink transition-colors"
              >
                {t('auth.backToSignIn')}
              </button>
            </form>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              {/* Email */}
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-ink-soft mb-2">
                  {t('auth.email')}
                </label>
                <div className="relative group">
                  <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none">
                    <Mail className="w-5 h-5 text-ink-muted group-focus-within:text-teal-600 transition-colors" />
                  </div>
                  <input
                    id="email" type="email" value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={inputCls}
                    placeholder="your.email@retaildemo.app"
                    autoComplete="email" disabled={isLoading}
                  />
                </div>
              </div>

              {/* Password */}
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-ink-soft mb-2">
                  {t('auth.password')}
                </label>
                <div className="relative group">
                  <div className="absolute inset-y-0 start-0 ps-4 flex items-center pointer-events-none">
                    <Lock className="w-5 h-5 text-ink-muted group-focus-within:text-teal-600 transition-colors" />
                  </div>
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`${inputCls} pe-12`}
                    placeholder="••••••••"
                    autoComplete="current-password" disabled={isLoading}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    aria-pressed={showPassword}
                    className="absolute inset-y-0 end-0 pe-4 flex items-center text-ink-muted hover:text-teal-600 transition-colors"
                  >
                    {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                  </button>
                </div>
              </div>

              {/* Remember / Forgot */}
              <div className="flex items-center justify-between">
                <label className="flex items-center cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={rememberMe}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    className="w-4 h-4 rounded border-line text-teal-600 focus:ring-teal-500/30 cursor-pointer accent-teal-600"
                    disabled={isLoading}
                  />
                  <span className="ms-2 text-sm text-ink-soft">{t('auth.rememberMe')}</span>
                </label>
                <button type="button" onClick={handleForgot} className="text-sm font-medium text-teal-700 hover:text-teal-800 dark:hover:text-teal-200 transition-colors">
                  {t('auth.forgot')}
                </button>
              </div>

              <SubmitButton isLoading={isLoading} idle={t('auth.signIn')} busy={t('auth.signingIn')} />
            </form>
          )}

          {/* Demo accounts */}
          <div className="mt-8">
            <div className="flex items-center gap-3 mb-3">
              <span className="h-px flex-1 bg-line" />
              <span className="text-xs font-medium text-ink-muted">{t('auth.tryDemo')}</span>
              <span className="h-px flex-1 bg-line" />
            </div>
            <div className="grid grid-cols-3 gap-2">
              {DEMO_ACCOUNTS.map((acc) => (
                <motion.button
                  key={acc.email}
                  type="button"
                  whileHover={{ y: -3 }}
                  whileTap={{ scale: 0.97 }}
                  transition={{ type: 'spring', stiffness: 320, damping: 24 }}
                  onClick={() => fillDemo(acc.email)}
                  disabled={isLoading}
                  className="rounded-2xl border border-line bg-surface p-3 text-start hover:border-teal-300 hover:shadow-card disabled:opacity-60"
                >
                  <div className={`w-7 h-7 rounded-lg ${acc.grad} mb-2`} />
                  <p className="text-xs font-semibold text-ink leading-tight">{t(acc.labelKey)}</p>
                  <p className="text-[10px] text-ink-muted truncate">{acc.email}</p>
                </motion.button>
              ))}
            </div>
            <p className="mt-3 text-center text-xs text-ink-muted">
              {t('auth.demoPassword')} <span className="font-mono font-medium text-ink-soft">Demo@2026!</span>
            </p>
          </div>

          <p className="mt-8 text-center text-sm text-ink-soft">
            {t('auth.newHere')}{' '}
            <Link href="/signup" className="font-semibold text-teal-700 hover:text-teal-800 dark:hover:text-teal-200">{t('auth.createWorkspace')}</Link>
          </p>
          <p className="mt-3 text-center">
            <Link href="/status" className="text-xs text-ink-muted hover:text-ink transition-colors">{t('status.title')}</Link>
          </p>
        </motion.div>
      </div>
    </div>
  );
}

/** Primary CTA with brand gradient, hover lift, and a loading state. */
function SubmitButton({ isLoading, idle, busy }: { isLoading: boolean; idle: string; busy: string }) {
  return (
    <motion.button
      type="submit"
      disabled={isLoading}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.99 }}
      transition={{ type: 'spring', stiffness: 320, damping: 24 }}
      className="sunset-gradient text-white w-full py-3.5 px-4 rounded-2xl font-semibold flex items-center justify-center gap-2 shadow-soft disabled:opacity-60 disabled:cursor-not-allowed"
    >
      {isLoading ? (
        <><Loader2 className="w-5 h-5 animate-spin" /> {busy}</>
      ) : (
        <>{idle} <ArrowRight className="w-5 h-5" /></>
      )}
    </motion.button>
  );
}
