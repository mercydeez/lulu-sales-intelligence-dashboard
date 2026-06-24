'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { PRODUCT_NAME } from '@/lib/brand';
import {
  Eye, EyeOff, Lock, Mail, AlertCircle, Loader2, ShoppingBag,
  TrendingUp, ShieldCheck, Activity, Sparkles, ArrowRight, KeyRound,
} from 'lucide-react';

const DEMO_ACCOUNTS = [
  { label: 'Super Admin', email: 'atharva@retaildemo.app', accent: 'from-coral-500 to-violet-500' },
  { label: 'Regional Mgr', email: 'krishna@retaildemo.app', accent: 'from-violet-500 to-teal-400' },
  { label: 'Store Mgr', email: 'yash@retaildemo.app', accent: 'from-amber-400 to-coral-500' },
];

export default function LoginPage() {
  const router = useRouter();
  const { login, verifyTwoFactor, isLoading, error, clearError } = useAuth();

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
      setLocalError('Please enter both email and password');
      return;
    }

    const res = await login({ email, password, remember_me: rememberMe });
    if (res.ok) router.push('/');
    else if (res.requires2fa && res.mfaToken) setMfaToken(res.mfaToken);
  };

  const handleVerify = async (e: FormEvent) => {
    e.preventDefault();
    setLocalError('');
    clearError();
    if (code.replace(/\s/g, '').length < 6) {
      setLocalError('Enter the 6-digit code from your authenticator app');
      return;
    }
    const ok = await verifyTwoFactor(mfaToken!, code.replace(/\s/g, ''));
    if (ok) router.push('/');
  };

  const [forgotMsg, setForgotMsg] = useState('');
  const handleForgot = async () => {
    setForgotMsg(''); setLocalError('');
    if (!email) { setLocalError('Enter your email above, then click “Forgot password?”'); return; }
    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      await fetch(`${API_URL}/api/auth/forgot-password`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
    } catch { /* ignore — generic message either way */ }
    setForgotMsg('If that account exists, a password reset link has been sent.');
  };

  const fillDemo = (demoEmail: string) => {
    setEmail(demoEmail);
    setPassword('Demo@2026!');
    setLocalError('');
    clearError();
  };

  const displayError = error || localError;

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      {/* ============================= BRAND PANEL ============================= */}
      <div className="relative hidden lg:flex flex-col justify-between overflow-hidden sunset-gradient p-12 text-white">
        {/* Decorative blobs */}
        <div className="blob w-96 h-96 bg-amber-300/50 -top-20 -left-16 animate-blob" />
        <div className="blob w-80 h-80 bg-teal-300/40 bottom-10 -right-10 animate-blob" style={{ animationDelay: '3s' }} />
        <div className="blob w-72 h-72 bg-violet-400/40 top-1/2 left-1/3 animate-blob" style={{ animationDelay: '6s' }} />

        {/* Brand */}
        <div className="relative z-10 flex items-center gap-3">
          <div className="flex items-center justify-center w-12 h-12 rounded-2xl bg-surface/20 backdrop-blur-sm ring-1 ring-white/30">
            <ShoppingBag className="w-6 h-6" />
          </div>
          <span className="text-xl font-bold tracking-tight">{PRODUCT_NAME}</span>
        </div>

        {/* Hero copy */}
        <div className="relative z-10 max-w-md">
          <div className="inline-flex items-center gap-2 rounded-full bg-surface/15 px-3 py-1 text-xs font-medium backdrop-blur-sm ring-1 ring-white/25 mb-5">
            <Sparkles className="w-3.5 h-3.5" /> Real-time retail analytics
          </div>
          <h1 className="text-4xl font-bold leading-tight mb-4">
            Every sale, every store, the moment it happens.
          </h1>
          <p className="text-white/85 text-lg leading-relaxed">
            Live KPIs, demand forecasting, and inventory intelligence across the
            Meridian Hypermarket UAE network — in one playful, powerful dashboard.
          </p>

          {/* Feature pills */}
          <div className="mt-8 space-y-3">
            {[
              { icon: Activity, text: 'Live sales stream updating every few seconds' },
              { icon: TrendingUp, text: 'Seasonal demand forecasts with accuracy scoring' },
              { icon: ShieldCheck, text: 'Role-based access scoped to your stores' },
            ].map(({ icon: Icon, text }) => (
              <div key={text} className="flex items-center gap-3">
                <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-surface/15 backdrop-blur-sm ring-1 ring-white/25">
                  <Icon className="w-4 h-4" />
                </div>
                <span className="text-white/90 text-sm">{text}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="relative z-10 text-white/70 text-xs">
          Independent student project · synthetic data · © 2026 Meridian Hypermarket UAE
        </div>
      </div>

      {/* ============================= FORM PANEL ============================= */}
      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md">
          {/* Mobile brand */}
          <div className="lg:hidden text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl sunset-gradient mb-4 shadow-sunset">
              <ShoppingBag className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-2xl font-bold gradient-text">{PRODUCT_NAME}</h1>
            <p className="text-ink-muted text-sm">UAE Sales Analytics Dashboard</p>
          </div>

          <div className="mb-8">
            <h2 className="text-3xl font-bold text-ink mb-2">Welcome back 👋</h2>
            <p className="text-ink-soft">Sign in to your analytics workspace.</p>
          </div>

          {/* Error Alert */}
          {displayError && (
            <div className="mb-6 p-4 rounded-2xl bg-coral-50 border border-coral-200 flex items-start gap-3 animate-fade-in">
              <AlertCircle className="w-5 h-5 text-coral-600 flex-shrink-0 mt-0.5" />
              <p className="text-coral-700 text-sm">{displayError}</p>
            </div>
          )}
          {forgotMsg && (
            <div className="mb-6 p-4 rounded-2xl bg-teal-50 border border-teal-200 flex items-start gap-3 animate-fade-in">
              <ShieldCheck className="w-5 h-5 text-teal-600 flex-shrink-0 mt-0.5" />
              <p className="text-teal-700 text-sm">{forgotMsg}</p>
            </div>
          )}

          {mfaToken ? (
            <form onSubmit={handleVerify} className="space-y-5">
              <div className="flex items-center gap-3 p-4 rounded-2xl bg-teal-50 border border-teal-100">
                <ShieldCheck className="w-5 h-5 text-teal-600 shrink-0" />
                <p className="text-sm text-teal-800">
                  Two-step verification is on. Enter the 6-digit code from your authenticator app.
                </p>
              </div>
              <div>
                <label htmlFor="code" className="block text-sm font-medium text-ink-soft mb-2">
                  Authentication code
                </label>
                <div className="relative group">
                  <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                    <KeyRound className="w-5 h-5 text-ink-muted group-focus-within:text-coral-500 transition-colors" />
                  </div>
                  <input
                    id="code"
                    inputMode="numeric"
                    autoFocus
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, '').slice(0, 7))}
                    className="w-full pl-12 pr-4 py-3.5 rounded-2xl bg-surface border border-coral-100 text-ink tracking-[0.4em] text-lg placeholder-ink-muted shadow-sm focus:outline-none focus:ring-4 focus:ring-coral-500/15 focus:border-coral-400 transition-all"
                    placeholder="123456"
                    autoComplete="one-time-code"
                    disabled={isLoading}
                  />
                </div>
              </div>
              <button
                type="submit"
                disabled={isLoading}
                className="btn-sunset w-full py-3.5 px-4 rounded-2xl font-semibold flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {isLoading ? (<><Loader2 className="w-5 h-5 animate-spin" /> Verifying...</>) : (<>Verify <ArrowRight className="w-5 h-5" /></>)}
              </button>
              <button
                type="button"
                onClick={() => { setMfaToken(null); setCode(''); setLocalError(''); clearError(); }}
                className="w-full text-sm font-medium text-ink-muted hover:text-ink transition-colors"
              >
                ← Back to sign in
              </button>
            </form>
          ) : (
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-ink-soft mb-2">
                Email Address
              </label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <Mail className="w-5 h-5 text-ink-muted group-focus-within:text-coral-500 transition-colors" />
                </div>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-12 pr-4 py-3.5 rounded-2xl bg-surface border border-coral-100 text-ink placeholder-ink-muted shadow-sm focus:outline-none focus:ring-4 focus:ring-coral-500/15 focus:border-coral-400 transition-all"
                  placeholder="your.email@retaildemo.app"
                  autoComplete="email"
                  disabled={isLoading}
                />
              </div>
            </div>

            {/* Password */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-ink-soft mb-2">
                Password
              </label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <Lock className="w-5 h-5 text-ink-muted group-focus-within:text-coral-500 transition-colors" />
                </div>
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full pl-12 pr-12 py-3.5 rounded-2xl bg-surface border border-coral-100 text-ink placeholder-ink-muted shadow-sm focus:outline-none focus:ring-4 focus:ring-coral-500/15 focus:border-coral-400 transition-all"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  disabled={isLoading}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-4 flex items-center text-ink-muted hover:text-coral-500 transition-colors"
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
                  className="w-4 h-4 rounded border-coral-200 text-coral-500 focus:ring-coral-500/30 cursor-pointer accent-coral-500"
                  disabled={isLoading}
                />
                <span className="ml-2 text-sm text-ink-soft">Remember me</span>
              </label>
              <button type="button" onClick={handleForgot} className="text-sm font-medium text-violet-600 hover:text-coral-500 transition-colors">
                Forgot password?
              </button>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={isLoading}
              className="btn-sunset w-full py-3.5 px-4 rounded-2xl font-semibold flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" /> Signing in...
                </>
              ) : (
                <>
                  Sign In <ArrowRight className="w-5 h-5" />
                </>
              )}
            </button>
          </form>
          )}

          {/* Demo accounts */}
          <div className="mt-8">
            <div className="flex items-center gap-3 mb-3">
              <span className="h-px flex-1 bg-coral-100" />
              <span className="text-xs font-medium text-ink-muted">Try a demo account</span>
              <span className="h-px flex-1 bg-coral-100" />
            </div>
            <div className="grid grid-cols-3 gap-2">
              {DEMO_ACCOUNTS.map((acc) => (
                <button
                  key={acc.email}
                  type="button"
                  onClick={() => fillDemo(acc.email)}
                  disabled={isLoading}
                  className="card-pop rounded-2xl border border-coral-100 bg-surface p-3 text-left hover:border-coral-300 disabled:opacity-60"
                >
                  <div className={`w-7 h-7 rounded-lg bg-gradient-to-br ${acc.accent} mb-2`} />
                  <p className="text-xs font-semibold text-ink leading-tight">{acc.label}</p>
                  <p className="text-[10px] text-ink-muted truncate">{acc.email}</p>
                </button>
              ))}
            </div>
            <p className="mt-3 text-center text-xs text-ink-muted">
              Password for all demos: <span className="font-mono font-medium text-ink-soft">Demo@2026!</span>
            </p>
          </div>

          <p className="mt-8 text-center text-sm text-ink-soft">
            New here?{' '}
            <Link href="/signup" className="font-medium gradient-text">Create your workspace</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
