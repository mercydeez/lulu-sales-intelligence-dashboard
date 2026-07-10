'use client';

import { useState, FormEvent } from 'react';
import { motion } from 'framer-motion';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { PRODUCT_NAME } from '@/lib/brand';
import {
  Eye, EyeOff, Lock, Mail, User, Building2, AlertCircle, Loader2,
  ShoppingBag, Rocket, Sparkles, ArrowRight, CheckCircle2,
} from 'lucide-react';

export default function SignupPage() {
  const router = useRouter();
  const { signup, isLoading, error, clearError } = useAuth();

  const [company, setCompany] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [seedSample, setSeedSample] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [localError, setLocalError] = useState('');

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLocalError('');
    clearError();

    if (!company || !firstName || !lastName || !email || !password) {
      setLocalError('Please fill in every field.');
      return;
    }
    if (password.length < 12) {
      setLocalError('Password must be at least 12 characters, with upper/lower/number/special.');
      return;
    }

    const success = await signup({
      company_name: company,
      first_name: firstName,
      last_name: lastName,
      email,
      password,
      seed_sample_data: seedSample,
    });
    if (success) router.push('/');
  };

  const displayError = error || localError;

  // Shared input treatment — mirrors the login screen so the two auth surfaces
  // read as one system (rounded-2xl, soft 4px focus ring, brand focus border).
  const inputBase =
    'w-full py-3.5 rounded-2xl bg-surface border border-line text-ink placeholder-ink-muted ' +
    'shadow-sm focus:outline-none focus:ring-4 focus:ring-teal-500/15 focus:border-teal-500 transition-all';
  const iconCls = 'w-5 h-5 text-ink-muted group-focus-within:text-teal-600 transition-colors';

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      {/* ============================= BRAND PANEL ============================= */}
      <div className="relative hidden lg:flex flex-col justify-between overflow-hidden sunset-gradient p-12 text-white">
        <div className="blob w-96 h-96 bg-amber-300/50 -top-20 -left-16 animate-blob" />
        <div className="blob w-80 h-80 bg-teal-300/40 bottom-10 -right-10 animate-blob" style={{ animationDelay: '3s' }} />

        <div className="relative z-10 flex items-center gap-3">
          <div className="flex items-center justify-center w-12 h-12 rounded-2xl bg-surface/20 backdrop-blur-sm ring-1 ring-white/30">
            <ShoppingBag className="w-6 h-6" />
          </div>
          <span className="text-xl font-bold tracking-tight">{PRODUCT_NAME}</span>
        </div>

        <div className="relative z-10 max-w-md">
          <div className="inline-flex items-center gap-2 rounded-full bg-surface/15 px-3 py-1 text-xs font-medium backdrop-blur-sm ring-1 ring-white/25 mb-5">
            <Rocket className="w-3.5 h-3.5" /> Start free — no card required
          </div>
          <h1 className="text-4xl font-bold leading-tight mb-4">
            Your own retail-intelligence workspace in 60 seconds.
          </h1>
          <p className="text-white/85 text-lg leading-relaxed">
            Spin up an isolated workspace with live KPIs, demand forecasting, and
            inventory intelligence. Start with sample data, connect your own when ready.
          </p>
          <div className="mt-8 space-y-3">
            {[
              'Your own isolated tenant — your data stays yours',
              'Pre-loaded sample data so the dashboard works on day one',
              'Forecasting, reorder suggestions, and an AI assistant built in',
            ].map((text) => (
              <div key={text} className="flex items-center gap-3">
                <CheckCircle2 className="w-5 h-5 text-white/90 flex-shrink-0" />
                <span className="text-white/90 text-sm">{text}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="relative z-10 text-white/70 text-xs">
          Independent student project · synthetic demo data (Meridian Hypermarket UAE) · © 2026 Retail Intelligence
        </div>
      </div>

      {/* ============================= FORM PANEL ============================= */}
      <div className="flex items-center justify-center p-6 sm:p-12">
        <motion.div
          className="w-full max-w-md"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="lg:hidden text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl sunset-gradient mb-4 shadow-sunset">
              <ShoppingBag className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-ink">{PRODUCT_NAME}</h1>
          </div>

          <div className="mb-8">
            <h2 className="text-3xl font-bold text-ink mb-2">Create your workspace</h2>
            <p className="text-ink-soft">Free trial — set up your team in minutes.</p>
          </div>

          {displayError && (
            <div className="mb-6 p-4 rounded-2xl bg-rose-50 border border-rose-200 flex items-start gap-3 animate-fade-in">
              <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
              <p className="text-rose-700 text-sm">{displayError}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="company" className="block text-sm font-medium text-ink-soft mb-2">Company name</label>
              <div className="relative group">
                <Building2 className={`absolute start-3.5 top-1/2 -translate-y-1/2 ${iconCls}`} />
                <input id="company" type="text" value={company} onChange={(e) => setCompany(e.target.value)}
                  className={`${inputBase} ps-11 pe-4`}
                  placeholder="Acme Retail" autoComplete="organization" />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="first" className="block text-sm font-medium text-ink-soft mb-2">First name</label>
                <div className="relative group">
                  <User className={`absolute start-3.5 top-1/2 -translate-y-1/2 ${iconCls}`} />
                  <input id="first" type="text" value={firstName} onChange={(e) => setFirstName(e.target.value)}
                    className={`${inputBase} ps-11 pe-3`}
                    placeholder="Nadia" autoComplete="given-name" />
                </div>
              </div>
              <div>
                <label htmlFor="last" className="block text-sm font-medium text-ink-soft mb-2">Last name</label>
                <input id="last" type="text" value={lastName} onChange={(e) => setLastName(e.target.value)}
                  className={`${inputBase} px-4`}
                  placeholder="Al Mansouri" autoComplete="family-name" />
              </div>
            </div>

            <div>
              <label htmlFor="email" className="block text-sm font-medium text-ink-soft mb-2">Work email</label>
              <div className="relative group">
                <Mail className={`absolute start-3.5 top-1/2 -translate-y-1/2 ${iconCls}`} />
                <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                  className={`${inputBase} ps-11 pe-4`}
                  placeholder="you@company.com" autoComplete="email" />
              </div>
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-ink-soft mb-2">Password</label>
              <div className="relative group">
                <Lock className={`absolute start-3.5 top-1/2 -translate-y-1/2 ${iconCls}`} />
                <input id="password" type={showPassword ? 'text' : 'password'} value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className={`${inputBase} ps-11 pe-11`}
                  placeholder="At least 12 characters" autoComplete="new-password" />
                <button type="button" onClick={() => setShowPassword((s) => !s)}
                  className="absolute end-3.5 top-1/2 -translate-y-1/2 text-ink-muted hover:text-teal-600 transition-colors">
                  {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>
              <p className="mt-1.5 text-xs text-ink-muted">12+ chars with upper, lower, number &amp; special character.</p>
            </div>

            <label className="flex items-center gap-3 cursor-pointer select-none">
              <input type="checkbox" checked={seedSample} onChange={(e) => setSeedSample(e.target.checked)}
                className="w-4 h-4 rounded border-line text-teal-600 focus:ring-teal-500/30 accent-teal-600" />
              <span className="text-sm text-ink-soft">Pre-load sample data so I can explore right away</span>
            </label>

            <button type="submit" disabled={isLoading}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-2xl sunset-gradient text-white font-semibold shadow-sunset hover:opacity-95 active:scale-[0.99] disabled:opacity-60 transition">
              {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <>Create workspace <ArrowRight className="w-4 h-4" /></>}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-ink-soft">
            Already have an account?{' '}
            <Link href="/login" className="font-semibold text-teal-700 hover:text-teal-800 dark:hover:text-teal-200 inline-flex items-center gap-1">
              Sign in <Sparkles className="w-3.5 h-3.5" />
            </Link>
          </p>
        </motion.div>
      </div>
    </div>
  );
}
