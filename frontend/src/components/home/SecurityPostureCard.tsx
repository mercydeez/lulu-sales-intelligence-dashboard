'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ShieldCheck, ShieldAlert, Shield, ChevronRight } from 'lucide-react';
import { Card } from '@/components/ui';
import { fetchSecurityKpi, SecurityKpi } from '@/lib/api';

const STATUS = {
  ok: { label: 'Secure', cls: 'text-teal-700', bg: 'bg-teal-50', Icon: ShieldCheck, bar: 'bg-teal-500' },
  watch: { label: 'Watch', cls: 'text-amber-700', bg: 'bg-amber-50', Icon: Shield, bar: 'bg-amber-500' },
  alert: { label: 'Alert', cls: 'text-rose-700', bg: 'bg-rose-50', Icon: ShieldAlert, bar: 'bg-rose-500' },
};

/** Compact security-posture tile for the dashboard (super_admin). Links to /security. */
export default function SecurityPostureCard() {
  const [kpi, setKpi] = useState<SecurityKpi | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const data = await fetchSecurityKpi();
        if (active) setKpi(data);
      } catch {
        /* leave empty on failure */
      }
    };
    load();
    const id = setInterval(load, 30000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const st = STATUS[kpi?.status ?? 'ok'];
  const score = kpi?.posture_score ?? 100;

  return (
    <Link href="/security" className="block group">
      <Card variant="glass" padding="md" className="transition-shadow group-hover:shadow-md">
        <div className="flex items-center gap-4">
          <div className={`p-3 rounded-xl ${st.bg} ${st.cls}`}><st.Icon className="w-6 h-6" /></div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-ink">Security posture</span>
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${st.bg} ${st.cls}`}>{st.label}</span>
            </div>
            <div className="mt-2 h-1.5 w-full rounded-full bg-line overflow-hidden">
              <div className={`h-full rounded-full ${st.bar} transition-all`} style={{ width: `${score}%` }} />
            </div>
            <div className="mt-1.5 text-xs text-ink-muted">
              Score {score}/100 · {kpi?.threats_active ?? 0} active threat{(kpi?.threats_active ?? 0) === 1 ? '' : 's'} · {kpi?.events_24h ?? 0} events (24h)
            </div>
          </div>
          <ChevronRight className="w-5 h-5 text-ink-muted group-hover:text-ink shrink-0" />
        </div>
      </Card>
    </Link>
  );
}
