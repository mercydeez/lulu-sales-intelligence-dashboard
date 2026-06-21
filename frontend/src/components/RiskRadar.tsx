'use client';

/**
 * Risk Radar (Phase 3 — proactive intelligence). Surfaces what's going wrong or
 * about to go wrong: forecast-driven stockouts, demand drops, return spikes, and
 * dead stock — ranked by severity. Findings come from the scheduled risk scans
 * (services/intelligence/risk_scans.py), so this is anticipatory, not reactive.
 */
import { useEffect, useState } from 'react';
import { AlertTriangle, TrendingDown, RotateCcw, PackageX, ShieldCheck } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { Card } from '@/components/ui';

interface Finding {
  id: number;
  type: string;
  severity: 'high' | 'medium' | 'low' | string;
  title: string;
  detail?: string;
}

const TYPE_ICON: Record<string, React.ReactNode> = {
  stockout_risk: <PackageX className="w-4 h-4" />,
  demand_drop: <TrendingDown className="w-4 h-4" />,
  return_spike: <RotateCcw className="w-4 h-4" />,
  dead_stock: <PackageX className="w-4 h-4" />,
};

const SEV_STYLE: Record<string, string> = {
  high: 'bg-red-50 text-red-700 border-red-200',
  medium: 'bg-amber-50 text-amber-700 border-amber-200',
  low: 'bg-slate-50 text-slate-600 border-slate-200',
};

export default function RiskRadar() {
  const { authFetch } = useAuth();
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [bySeverity, setBySeverity] = useState<Record<string, number>>({});

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const r = await authFetch('/api/intelligence/risks?limit=8');
        if (!r.ok) { if (active) setFindings([]); return; }
        const data = await r.json();
        if (active) { setFindings(data.findings ?? []); setBySeverity(data.by_severity ?? {}); }
      } catch {
        if (active) setFindings([]);
      }
    };
    load();
    const t = setInterval(load, 60_000); // refresh as scans land
    return () => { active = false; clearInterval(t); };
  }, [authFetch]);

  if (findings === null) return null; // loading — stay quiet

  return (
    <Card padding="lg" className="mb-6 border border-amber-100">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle className="w-5 h-5 text-amber-500" />
        <h3 className="text-base font-medium text-ink">Risk Radar</h3>
        <span className="text-xs text-ink-muted">· what&apos;s going wrong</span>
        {(bySeverity.high ?? 0) > 0 && (
          <span className="ml-auto text-xs font-medium px-2 py-0.5 rounded-full bg-red-50 text-red-700 border border-red-200">
            {bySeverity.high} high
          </span>
        )}
      </div>

      {findings.length === 0 ? (
        <div className="flex items-center gap-2 p-3 text-sm text-ink-muted">
          <ShieldCheck className="w-4 h-4 text-teal-500" />
          No active risks detected — operations look healthy.
        </div>
      ) : (
        <div className="space-y-2">
          {findings.map((f) => (
            <div key={f.id} className="flex items-start gap-3 p-3 rounded-xl hover:bg-[#faf7f3] transition-colors">
              <span className="mt-0.5 text-ink-muted">{TYPE_ICON[f.type] ?? <AlertTriangle className="w-4 h-4" />}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-ink font-medium truncate">{f.title}</span>
                  <span className={`text-[10px] uppercase px-1.5 py-0.5 rounded border ${SEV_STYLE[f.severity] ?? SEV_STYLE.low}`}>
                    {f.severity}
                  </span>
                </div>
                {f.detail && <p className="text-xs text-ink-muted mt-0.5 line-clamp-2">{f.detail}</p>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
