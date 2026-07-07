'use client';

/**
 * Public system-status page (CX trust loop — docs/product/CX_LOOPS_PLAN.md Y4).
 * Binds to the real health probes (`/api/monitoring/live` + `/ready`) — no
 * marketing layer, the page says what the platform says. Polls gently (60s)
 * so a thousand open tabs cannot become a self-inflicted load test; swaps to
 * Krishna's cached `public-status` endpoint (K2) when it lands.
 */
import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Activity, CheckCircle2, AlertTriangle, XCircle, Database, Globe, ShieldCheck } from 'lucide-react';
import { useLanguage } from '@/contexts/LanguageContext';
import { PRODUCT_NAME } from '@/lib/brand';
import { track } from '@/lib/telemetry';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const POLL_MS = 60_000;

type ComponentState = 'operational' | 'down' | 'checking';

interface Component {
  key: string;
  label: string;
  icon: typeof Activity;
  state: ComponentState;
}

/** Recorded incidents, newest first — append honestly, never delete. */
const INCIDENTS: { date: string; title: string; summary: string }[] = [];

function StateIcon({ state }: { state: ComponentState }) {
  if (state === 'operational') return <CheckCircle2 className="w-5 h-5 text-teal-600" />;
  if (state === 'down') return <XCircle className="w-5 h-5 text-rose-500" />;
  return <span className="w-5 h-5 rounded-full border-2 border-line border-t-teal-500 animate-spin inline-block" />;
}

export default function StatusPage() {
  const { t } = useLanguage();
  const [api, setApi] = useState<ComponentState>('checking');
  const [data, setData] = useState<ComponentState>('checking');
  const [lastChecked, setLastChecked] = useState<string | null>(null);

  const check = useCallback(async () => {
    const probe = async (path: string): Promise<ComponentState> => {
      try {
        const res = await fetch(`${API_URL}${path}`, { cache: 'no-store' });
        return res.ok ? 'operational' : 'down';
      } catch {
        return 'down';
      }
    };
    const [live, ready] = await Promise.all([
      probe('/api/monitoring/live'),
      probe('/api/monitoring/ready'),
    ]);
    setApi(live);
    setData(ready);
    setLastChecked(new Date().toLocaleTimeString());
  }, []);

  useEffect(() => {
    track('status_page_viewed');
    check();
    const id = setInterval(check, POLL_MS);
    return () => clearInterval(id);
  }, [check]);

  const components: Component[] = [
    // The app rendered this page, so it is operational by construction.
    { key: 'app', label: t('status.component.app'), icon: Globe, state: 'operational' },
    { key: 'api', label: t('status.component.api'), icon: Activity, state: api },
    { key: 'data', label: 'Data platform (PostgreSQL · Redis)', icon: Database, state: data },
  ];

  const anyChecking = components.some((c) => c.state === 'checking');
  const downCount = components.filter((c) => c.state === 'down').length;
  const overall =
    anyChecking ? 'checking' : downCount === 0 ? 'operational' : downCount < components.length ? 'degraded' : 'down';

  const banner = {
    operational: { text: t('status.operational'), cls: 'bg-teal-50 dark:bg-teal-500/10 border-teal-200 text-teal-700 dark:text-teal-300', icon: CheckCircle2 },
    degraded: { text: t('status.degraded'), cls: 'bg-amber-50 dark:bg-amber-500/10 border-amber-200 text-amber-700 dark:text-amber-300', icon: AlertTriangle },
    down: { text: t('status.down'), cls: 'bg-rose-50 dark:bg-rose-500/10 border-rose-200 text-rose-700 dark:text-rose-300', icon: XCircle },
    checking: { text: t('status.checking'), cls: 'bg-surface-2 border-line text-ink-soft', icon: Activity },
  }[overall];
  const BannerIcon = banner.icon;

  return (
    <main className="min-h-screen p-6 sm:p-12">
      <div className="max-w-2xl mx-auto">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
          <div className="flex items-center gap-3 mb-2">
            <Activity className="w-6 h-6 text-teal-600" />
            <h1 className="text-2xl font-bold text-ink">
              {PRODUCT_NAME} — {t('status.title')}
            </h1>
          </div>
          <p className="text-ink-muted text-sm mb-8">{t('status.description')}</p>

          <div className={`flex items-center gap-3 rounded-2xl border px-5 py-4 mb-8 ${banner.cls}`}>
            <BannerIcon className="w-5 h-5" />
            <span className="font-semibold">{banner.text}</span>
            {lastChecked && (
              <span className="ms-auto text-xs opacity-80 tabular-nums">
                {t('status.lastChecked')}: {lastChecked}
              </span>
            )}
          </div>

          <ul className="space-y-3 mb-10">
            {components.map((c) => {
              const Icon = c.icon;
              return (
                <li key={c.key} className="flex items-center gap-4 rounded-xl border border-line bg-surface px-5 py-4">
                  <Icon className="w-5 h-5 text-ink-muted" />
                  <span className="flex-1 text-sm font-medium text-ink">{c.label}</span>
                  <StateIcon state={c.state} />
                </li>
              );
            })}
          </ul>

          <section className="mb-10">
            <h2 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-3">{t('status.commitment')}</h2>
            <div className="rounded-xl border border-line bg-surface px-5 py-4 flex items-start gap-3">
              <ShieldCheck className="w-5 h-5 text-teal-600 shrink-0 mt-0.5" />
              <p className="text-sm text-ink-soft leading-relaxed">
                Nightly encrypted backups with a restore that is rehearsed automatically on every
                code change — not just taken, but proven restorable. Row-level tenant isolation is
                enforced in the database itself. Details live in our trust center.
              </p>
            </div>
          </section>

          <section>
            <h2 className="text-sm font-semibold text-ink-soft uppercase tracking-wide mb-3">{t('status.incidents')}</h2>
            {INCIDENTS.length === 0 ? (
              <p className="text-sm text-ink-muted">{t('status.noIncidents')}</p>
            ) : (
              <ul className="space-y-3">
                {INCIDENTS.map((inc) => (
                  <li key={inc.date + inc.title} className="rounded-xl border border-line bg-surface px-5 py-4">
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <p className="text-sm font-medium text-ink">{inc.title}</p>
                      <span className="text-xs text-ink-muted tabular-nums">{inc.date}</span>
                    </div>
                    <p className="text-xs text-ink-soft">{inc.summary}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </motion.div>
      </div>
    </main>
  );
}
