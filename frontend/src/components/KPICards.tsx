'use client';

import { useEffect, useState } from 'react';
import {
  Database,
  Activity,
  Calendar,
  Clock,
  Zap,
  BarChart3,
  Info,
  X
} from 'lucide-react';
import { formatCurrency, formatCurrencyCompact } from '@/lib/formatters';
import { StatCard, LiveIndicator, AnimatedNumber, ErrorState } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';

interface KPIData {
  total_historical_records: number;
  total_streaming_records: number;
  total_sales_today: number;
  total_sales_week: number;
  total_sales_month: number;
  average_daily_sales: number;
  total_revenue_today: number;
  total_revenue_week: number;
  total_revenue_month: number;
  average_daily_revenue: number;
  unique_stores: number;
  unique_items: number;
  data_range_start: string | null;
  data_range_end: string | null;
  last_stream_timestamp: string | null;
  sales_trend: 'up' | 'down' | 'stable';
  revenue_trend: 'up' | 'down' | 'stable';
}

interface KPICardsProps {
  refreshInterval?: number;
}

type TooltipTone = 'coral' | 'teal' | 'violet' | 'amber';

interface TooltipProps {
  title: string;
  description: string;
  details?: string[];
  tone: TooltipTone;
  icon: React.ReactNode;
}

const tooltipToneClasses: Record<TooltipTone, { border: string; iconBg: string }> = {
  coral: { border: 'border-coral-200', iconBg: 'bg-coral-100' },
  teal: { border: 'border-teal-200', iconBg: 'bg-teal-100' },
  violet: { border: 'border-violet-200', iconBg: 'bg-violet-100' },
  amber: { border: 'border-amber-200', iconBg: 'bg-amber-100' },
};

function AnimatedTooltip({ title, description, details, tone, icon, onClose }: TooltipProps & { onClose: () => void }) {
  const toneClasses = tooltipToneClasses[tone];
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center animate-fade-in">
      <div className="absolute inset-0 bg-ink/30 backdrop-blur-sm rounded-2xl" onClick={onClose}></div>
      <div className={`relative bg-white rounded-xl p-4 mx-3 border ${toneClasses.border} shadow-2xl transform animate-scale-in`}>
        <button
          onClick={onClose}
          className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-coral-50 hover:bg-coral-100 flex items-center justify-center transition-colors"
        >
          <X className="w-3 h-3 text-ink-muted" />
        </button>
        <div className="flex items-start gap-3">
          <div className={`p-2 rounded-lg ${toneClasses.iconBg}`}>
            {icon}
          </div>
          <div>
            <h4 className="text-ink font-semibold text-sm">{title}</h4>
            <p className="text-ink-muted text-xs mt-1 max-w-[200px]">{description}</p>
            {details && details.length > 0 && (
              <ul className="mt-2 space-y-1">
                {details.map((detail, i) => (
                  <li key={i} className="text-xs text-ink-muted flex items-center gap-1">
                    <span className="w-1 h-1 rounded-full bg-ink-muted"></span>
                    {detail}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function InfoButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      className="opacity-0 group-hover:opacity-100 transition-opacity duration-200 p-1 rounded-full hover:bg-coral-50"
    >
      <Info className="w-3.5 h-3.5 text-ink-muted hover:text-ink transition-colors" />
    </button>
  );
}

function formatTimeAgo(timestamp: string | null): string {
  if (!timestamp) return 'Never';

  const now = new Date();
  const then = new Date(timestamp);
  const diffMs = now.getTime() - then.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);

  if (diffSecs < 10) return 'just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return then.toLocaleDateString();
}

export default function KPICards({ refreshInterval = 30000 }: KPICardsProps) {
  const { authFetch } = useAuth();
  const [kpis, setKpis] = useState<KPIData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nextRefresh, setNextRefresh] = useState(refreshInterval / 1000);
  const [mounted, setMounted] = useState(false);
  const [activeTooltip, setActiveTooltip] = useState<string | null>(null);

  const tooltipData: Record<string, TooltipProps> = {
    historical: {
      title: "Historical Records",
      description: "Total number of sales transactions from the imported CSV training dataset.",
      details: ["Pre-loaded from train.csv", "Spans multiple years", "Used for AI model training"],
      tone: "coral",
      icon: <Database className="w-4 h-4 text-coral-600" />
    },
    live: {
      title: "Live Streaming Records",
      description: "Real-time sales transactions generated by our streaming simulation engine.",
      details: ["Updates every 2-5 seconds", "SSE (Server-Sent Events)", "Includes returns (negative)"],
      tone: "teal",
      icon: <Zap className="w-4 h-4 text-teal-600" />
    },
    weekly: {
      title: "Weekly Sales Volume",
      description: "Total units (qty) sold across all stores and products in the last 7 days.",
      details: ["Rolling 7-day window", "Includes historical + live", "Trend compared to prior week"],
      tone: "violet",
      icon: <BarChart3 className="w-4 h-4 text-violet-600" />
    },
    daily: {
      title: "Average Daily Sales",
      description: "Mean sales volume per day calculated from the entire historical dataset.",
      details: ["Baseline metric", "Used for forecasting", "Per store breakdown available"],
      tone: "amber",
      icon: <Calendar className="w-4 h-4 text-amber-600" />
    },
    today: {
      title: "Today's Sales",
      description: "Current day sales volume combining both streaming and any historical data for today.",
      details: ["Real-time updates", "Resets at midnight", "Goal tracking enabled"],
      tone: "coral",
      icon: <Activity className="w-4 h-4 text-coral-600" />
    },
    monthly: {
      title: "Monthly Sales",
      description: "Aggregated sales volume for the rolling 30-day period.",
      details: ["30-day rolling window", "Month-over-month trends", "Executive reporting metric"],
      tone: "teal",
      icon: <Calendar className="w-4 h-4 text-teal-600" />
    },
    lastStream: {
      title: "Last Stream Event",
      description: "Timestamp of the most recent real-time data point received from the streaming service.",
      details: ["Monitors system health", "Alert if >30s stale", "Auto-reconnects on failure"],
      tone: "violet",
      icon: <Clock className="w-4 h-4 text-violet-600" />
    }
  };

  // Prevent hydration mismatch by only rendering time-dependent content on client
  useEffect(() => {
    setMounted(true);
  }, []);

  const loadKPIs = async () => {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);

      // No custom request headers here: a non-safelisted header like
      // Cache-Control forces a CORS preflight that must be allow-listed server
      // side, and getting that wrong surfaces as a confusing "Failed to fetch".
      const response = await authFetch('/api/kpis', {
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) throw new Error('Failed to fetch KPIs');
      const data = await response.json();
      setKpis(data);
      setError(null);
      setNextRefresh(refreshInterval / 1000);
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setError(err instanceof Error ? err.message : 'Error fetching KPIs');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadKPIs();
    const interval = setInterval(loadKPIs, refreshInterval);
    return () => clearInterval(interval);
  }, [refreshInterval, authFetch]);

  useEffect(() => {
    const countdown = setInterval(() => {
      setNextRefresh((prev) => (prev > 0 ? prev - 1 : refreshInterval / 1000));
    }, 1000);
    return () => clearInterval(countdown);
  }, [refreshInterval]);

  const getTrend = (trend: string): 'up' | 'down' | 'flat' => {
    if (trend === 'up') return 'up';
    if (trend === 'down') return 'down';
    return 'flat';
  };

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <StatCard key={i} label="" value="" loading />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="glass rounded-2xl">
        <ErrorState
          title="Couldn't load KPIs"
          description={error}
          onRetry={() => { setLoading(true); loadKPIs(); }}
        />
      </div>
    );
  }

  if (!kpis) return null;

  return (
    <div className="space-y-6">
      {/* Refresh Timer */}
      <div className="flex items-center justify-end gap-2 text-sm text-ink-muted">
        <Clock className="w-4 h-4" />
        <span>Next update in: {nextRefresh}s</span>
      </div>

      {/* Main KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Historical"
          tone="coral"
          icon={<Database className="w-5 h-5" />}
          value={<AnimatedNumber value={kpis.total_historical_records} />}
          footnote={`${kpis.data_range_start} → ${kpis.data_range_end}`}
        >
          <button onClick={() => setActiveTooltip('historical')} className="absolute top-4 right-4 z-10 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-full hover:bg-coral-50">
            <Info className="w-3.5 h-3.5 text-ink-muted hover:text-ink" />
          </button>
          {activeTooltip === 'historical' && (
            <AnimatedTooltip {...tooltipData.historical} onClose={() => setActiveTooltip(null)} />
          )}
        </StatCard>

        <StatCard
          label="Live"
          tone="teal"
          icon={<Zap className="w-5 h-5" />}
          value={<AnimatedNumber value={kpis.total_streaming_records} flashOnChange />}
          footnote={`Last: ${formatTimeAgo(kpis.last_stream_timestamp)}`}
        >
          <div className="absolute top-0 right-0 w-24 h-24 bg-teal-400/10 rounded-full blur-2xl" />
          <div className="absolute top-4 right-4 flex items-center gap-1.5">
            <InfoButton onClick={() => setActiveTooltip('live')} />
            <LiveIndicator tone="teal" size="sm" />
          </div>
          {activeTooltip === 'live' && (
            <AnimatedTooltip {...tooltipData.live} onClose={() => setActiveTooltip(null)} />
          )}
        </StatCard>

        <StatCard
          label={`Weekly Revenue • ${kpis.revenue_trend}`}
          tone="violet"
          icon={<BarChart3 className="w-5 h-5" />}
          value={<AnimatedNumber value={kpis.total_revenue_week} formatter={formatCurrencyCompact} />}
          trend={getTrend(kpis.revenue_trend)}
          footnote={`Volume: ${new Intl.NumberFormat().format(kpis.total_sales_week)} units`}
        >
          <button onClick={() => setActiveTooltip('weekly')} className="absolute top-4 right-10 z-10 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-full hover:bg-coral-50">
            <Info className="w-3.5 h-3.5 text-ink-muted hover:text-ink" />
          </button>
          {activeTooltip === 'weekly' && (
            <AnimatedTooltip {...tooltipData.weekly} onClose={() => setActiveTooltip(null)} />
          )}
        </StatCard>

        <StatCard
          label="Avg Daily Revenue"
          tone="amber"
          icon={<Calendar className="w-5 h-5" />}
          value={formatCurrencyCompact(kpis.average_daily_revenue)}
          footnote={
            <>
              Avg: {kpis.average_daily_sales.toFixed(0)} units/day
              <span className="text-ink-muted/80 text-xs block mt-0.5">
                {kpis.unique_stores} stores • {kpis.unique_items} items
              </span>
            </>
          }
        >
          <button onClick={() => setActiveTooltip('daily')} className="absolute top-4 right-4 z-10 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-full hover:bg-coral-50">
            <Info className="w-3.5 h-3.5 text-ink-muted hover:text-ink" />
          </button>
          {activeTooltip === 'daily' && (
            <AnimatedTooltip {...tooltipData.daily} onClose={() => setActiveTooltip(null)} />
          )}
        </StatCard>
      </div>

      {/* Secondary KPIs - Gradient Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard
          variant="gradient"
          tone="coral"
          label="Today's Revenue"
          value={<AnimatedNumber value={kpis.total_revenue_today} formatter={formatCurrency} />}
          footnote={`Volume: ${new Intl.NumberFormat().format(kpis.total_sales_today)} units`}
        >
          <button onClick={() => setActiveTooltip('today')} className="absolute top-4 right-4 z-10 p-1 rounded-full hover:bg-white/20">
            <Info className="w-3.5 h-3.5 text-white/80" />
          </button>
          {activeTooltip === 'today' && (
            <AnimatedTooltip {...tooltipData.today} onClose={() => setActiveTooltip(null)} />
          )}
        </StatCard>

        <StatCard
          variant="gradient"
          tone="violet"
          label="Monthly Revenue"
          value={<AnimatedNumber value={kpis.total_revenue_month} formatter={formatCurrencyCompact} />}
          footnote={`Volume: ${new Intl.NumberFormat().format(kpis.total_sales_month)} units`}
        >
          <button onClick={() => setActiveTooltip('monthly')} className="absolute top-4 right-4 z-10 p-1 rounded-full hover:bg-white/20">
            <Info className="w-3.5 h-3.5 text-white/80" />
          </button>
          {activeTooltip === 'monthly' && (
            <AnimatedTooltip {...tooltipData.monthly} onClose={() => setActiveTooltip(null)} />
          )}
        </StatCard>

        <StatCard
          variant="gradient"
          tone="teal"
          label="Last Stream"
          value={
            mounted && kpis.last_stream_timestamp
              ? new Date(kpis.last_stream_timestamp).toLocaleTimeString('en-US', {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                  hour12: true
                })
              : kpis.last_stream_timestamp ? '--:--:--' : 'No streams yet'
          }
          footnote={mounted ? formatTimeAgo(kpis.last_stream_timestamp) : '--'}
        >
          <button onClick={() => setActiveTooltip('lastStream')} className="absolute top-4 right-4 z-10 p-1 rounded-full hover:bg-white/20">
            <Info className="w-3.5 h-3.5 text-white/80" />
          </button>
          {activeTooltip === 'lastStream' && (
            <AnimatedTooltip {...tooltipData.lastStream} onClose={() => setActiveTooltip(null)} />
          )}
        </StatCard>
      </div>
    </div>
  );
}
