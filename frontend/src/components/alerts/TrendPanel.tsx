import { ChartFrame } from '@/components/ui';
import { AlertStats } from './types';

export interface TrendPanelProps {
  stats: AlertStats | null;
  loading: boolean;
}

export default function TrendPanel({ stats, loading }: TrendPanelProps) {
  const days = stats?.daily_stats ?? [];
  const maxAlerts = Math.max(...days.flatMap((d) => [d.critical, d.warning, d.info]), 1);

  return (
    <ChartFrame
      title="7-Day Trend"
      subtitle={stats ? `${stats.total_alerts} alerts · ${Math.round(stats.resolution_rate * 100)}% resolved` : undefined}
      loading={loading}
      empty={!loading && days.length === 0}
      height={300}
    >
      <div className="space-y-3 overflow-y-auto h-full pr-1">
        {days.map((day, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <span className="text-xs text-ink-muted w-10 shrink-0">
              {new Date(day.date).toLocaleDateString('en-AE', { weekday: 'short' })}
            </span>
            <div className="flex-1 flex gap-0.5 h-3.5">
              <div className="bg-rose-500 rounded-sm" style={{ width: `${(day.critical / maxAlerts) * 100}%` }} title={`${day.critical} critical`} />
              <div className="bg-amber-500 rounded-sm" style={{ width: `${(day.warning / maxAlerts) * 100}%` }} title={`${day.warning} warning`} />
              <div className="bg-violet-500 rounded-sm" style={{ width: `${(day.info / maxAlerts) * 100}%` }} title={`${day.info} info`} />
            </div>
            <span className="text-xs text-ink-muted w-6 text-end shrink-0">{day.critical + day.warning + day.info}</span>
          </div>
        ))}
        <div className="flex items-center justify-center gap-4 pt-2 text-xs text-ink-muted">
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-rose-500" /> Critical</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-amber-500" /> Warning</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-violet-500" /> Info</span>
        </div>
      </div>
    </ChartFrame>
  );
}
