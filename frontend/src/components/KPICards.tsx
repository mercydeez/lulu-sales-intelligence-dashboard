'use client';

import { useEffect, useState, useRef } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Minus, 
  Database, 
  Activity, 
  Calendar, 
  Store,
  Clock,
  Zap,
  BarChart3,
  Info,
  X
} from 'lucide-react';
import { formatCurrency, formatCurrencyCompact } from '@/lib/formatters';


const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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

// Animated tooltip component
interface TooltipProps {
  title: string;
  description: string;
  details?: string[];
  color: string;
  icon: React.ReactNode;
}

function AnimatedTooltip({ title, description, details, color, icon, onClose }: TooltipProps & { onClose: () => void }) {
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center animate-fade-in">
      <div className="absolute inset-0 bg-slate-900/80 backdrop-blur-sm rounded-2xl" onClick={onClose}></div>
      <div className={`relative bg-slate-900 rounded-xl p-4 mx-3 border ${color} shadow-2xl transform animate-scale-in`}>
        <button 
          onClick={onClose}
          className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-slate-700 hover:bg-slate-600 flex items-center justify-center transition-colors"
        >
          <X className="w-3 h-3 text-slate-300" />
        </button>
        <div className="flex items-start gap-3">
          <div className={`p-2 rounded-lg ${color.replace('border-', 'bg-').replace('/50', '/20')}`}>
            {icon}
          </div>
          <div>
            <h4 className="text-white font-semibold text-sm">{title}</h4>
            <p className="text-slate-400 text-xs mt-1 max-w-[200px]">{description}</p>
            {details && details.length > 0 && (
              <ul className="mt-2 space-y-1">
                {details.map((detail, i) => (
                  <li key={i} className="text-xs text-slate-500 flex items-center gap-1">
                    <span className="w-1 h-1 rounded-full bg-slate-500"></span>
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

// Info button that triggers tooltip
function InfoButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      className="opacity-0 group-hover:opacity-100 transition-opacity duration-200 p-1 rounded-full hover:bg-white/10"
    >
      <Info className="w-3.5 h-3.5 text-slate-400 hover:text-white transition-colors" />
    </button>
  );
}

// Animated counter component
function AnimatedNumber({ value, duration = 1000, formatter }: { value: number; duration?: number; formatter?: (val: number) => string }) {
  const [displayValue, setDisplayValue] = useState(0);
  const previousValue = useRef(0);

  useEffect(() => {
    const startValue = previousValue.current;
    const endValue = value;
    const startTime = Date.now();

    const animate = () => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);
      
      // Easing function for smooth animation
      const easeOutQuart = 1 - Math.pow(1 - progress, 4);
      const current = Math.floor(startValue + (endValue - startValue) * easeOutQuart);
      
      setDisplayValue(current);
      
      if (progress < 1) {
        requestAnimationFrame(animate);
      } else {
        previousValue.current = endValue;
      }
    };

    requestAnimationFrame(animate);
  }, [value, duration]);

  return <span>{formatter ? formatter(displayValue) : new Intl.NumberFormat().format(displayValue)}</span>;
}


// Time ago formatter
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
  const [kpis, setKpis] = useState<KPIData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nextRefresh, setNextRefresh] = useState(refreshInterval / 1000);
  const [mounted, setMounted] = useState(false);
  const [activeTooltip, setActiveTooltip] = useState<string | null>(null);

  // Tooltip content definitions
  const tooltipData: Record<string, TooltipProps> = {
    historical: {
      title: "Historical Records",
      description: "Total number of sales transactions from the imported CSV training dataset.",
      details: ["Pre-loaded from train.csv", "Spans multiple years", "Used for AI model training"],
      color: "border-cyan-500/50",
      icon: <Database className="w-4 h-4 text-cyan-400" />
    },
    live: {
      title: "Live Streaming Records",
      description: "Real-time sales transactions generated by our streaming simulation engine.",
      details: ["Updates every 2-5 seconds", "SSE (Server-Sent Events)", "Includes returns (negative)"],
      color: "border-emerald-500/50",
      icon: <Zap className="w-4 h-4 text-emerald-400" />
    },
    weekly: {
      title: "Weekly Sales Volume",
      description: "Total units (qty) sold across all stores and products in the last 7 days.",
      details: ["Rolling 7-day window", "Includes historical + live", "Trend compared to prior week"],
      color: "border-purple-500/50",
      icon: <BarChart3 className="w-4 h-4 text-purple-400" />
    },
    daily: {
      title: "Average Daily Sales",
      description: "Mean sales volume per day calculated from the entire historical dataset.",
      details: ["Baseline metric", "Used for forecasting", "Per store breakdown available"],
      color: "border-amber-500/50",
      icon: <Calendar className="w-4 h-4 text-amber-400" />
    },
    today: {
      title: "Today's Sales",
      description: "Current day sales volume combining both streaming and any historical data for today.",
      details: ["Real-time updates", "Resets at midnight", "Goal tracking enabled"],
      color: "border-cyan-500/50",
      icon: <Activity className="w-4 h-4 text-cyan-400" />
    },
    monthly: {
      title: "Monthly Sales",
      description: "Aggregated sales volume for the rolling 30-day period.",
      details: ["30-day rolling window", "Month-over-month trends", "Executive reporting metric"],
      color: "border-emerald-500/50",
      icon: <Calendar className="w-4 h-4 text-emerald-400" />
    },
    lastStream: {
      title: "Last Stream Event",
      description: "Timestamp of the most recent real-time data point received from the streaming service.",
      details: ["Monitors system health", "Alert if >30s stale", "Auto-reconnects on failure"],
      color: "border-purple-500/50",
      icon: <Clock className="w-4 h-4 text-purple-400" />
    }
  };

  // Prevent hydration mismatch by only rendering time-dependent content on client
  useEffect(() => {
    setMounted(true);
  }, []);

  const loadKPIs = async () => {
    try {
      // Use cached API with timeout
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);
      
      const response = await fetch(`${API_URL}/api/kpis`, {
        signal: controller.signal,
        headers: { 'Cache-Control': 'max-age=15' }
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
  }, [refreshInterval]);

  // Countdown timer
  useEffect(() => {
    const countdown = setInterval(() => {
      setNextRefresh((prev) => (prev > 0 ? prev - 1 : refreshInterval / 1000));
    }, 1000);
    return () => clearInterval(countdown);
  }, [refreshInterval]);

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case 'up':
        return <TrendingUp className="w-5 h-5 text-emerald-400" />;
      case 'down':
        return <TrendingDown className="w-5 h-5 text-rose-400" />;
      default:
        return <Minus className="w-5 h-5 text-slate-400" />;
    }
  };

  const getTrendColor = (trend: string) => {
    switch (trend) {
      case 'up': return 'text-emerald-400';
      case 'down': return 'text-rose-400';
      default: return 'text-slate-400';
    }
  };

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="glass rounded-2xl p-6 card-hover">
            <div className="h-4 shimmer rounded w-1/2 mb-4"></div>
            <div className="h-8 shimmer rounded w-3/4"></div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="glass rounded-2xl p-6 border border-rose-500/50">
        <div className="flex items-center gap-3 text-rose-400">
          <Activity className="w-5 h-5" />
          <span>Error loading KPIs: {error}</span>
        </div>
      </div>
    );
  }

  if (!kpis) return null;

  return (
    <div className="space-y-6">
      {/* Refresh Timer */}
      <div className="flex items-center justify-end gap-2 text-sm text-slate-400">
        <Clock className="w-4 h-4" />
        <span>Next update in: {nextRefresh}s</span>
      </div>

      {/* Main KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Historical Records */}
        <div className="glass rounded-2xl p-6 card-hover group relative overflow-hidden">
          {activeTooltip === 'historical' && (
            <AnimatedTooltip {...tooltipData.historical} onClose={() => setActiveTooltip(null)} />
          )}
          <div className="flex items-center justify-between mb-4">
            <div className="p-2 rounded-xl bg-cyan-500/20 group-hover:bg-cyan-500/30 transition-colors">
              <Database className="w-5 h-5 text-cyan-400" />
            </div>
            <div className="flex items-center gap-1">
              <InfoButton onClick={() => setActiveTooltip('historical')} />
              <span className="text-xs text-slate-500 uppercase tracking-wider">Historical</span>
            </div>
          </div>
          <div className="text-3xl font-bold text-white mb-1">
            <AnimatedNumber value={kpis.total_historical_records} />
          </div>
          <div className="text-sm text-slate-400">
            {kpis.data_range_start} → {kpis.data_range_end}
          </div>
        </div>

        {/* Streaming Records */}
        <div className="glass rounded-2xl p-6 card-hover group relative overflow-hidden">
          {activeTooltip === 'live' && (
            <AnimatedTooltip {...tooltipData.live} onClose={() => setActiveTooltip(null)} />
          )}
          <div className="absolute top-0 right-0 w-24 h-24 bg-emerald-500/10 rounded-full blur-2xl"></div>
          <div className="flex items-center justify-between mb-4 relative">
            <div className="p-2 rounded-xl bg-emerald-500/20 group-hover:bg-emerald-500/30 transition-colors">
              <Zap className="w-5 h-5 text-emerald-400" />
            </div>
            <div className="flex items-center gap-2">
              <InfoButton onClick={() => setActiveTooltip('live')} />
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <span className="text-xs text-emerald-400 uppercase tracking-wider">Live</span>
            </div>
          </div>
          <div className="text-3xl font-bold text-white mb-1 relative">
            <AnimatedNumber value={kpis.total_streaming_records} />
          </div>
          <div className="text-sm text-slate-400">
            Last: {formatTimeAgo(kpis.last_stream_timestamp)}
          </div>
        </div>

        {/* Weekly Revenue */}
        <div className="glass rounded-2xl p-6 card-hover group relative overflow-hidden">
          {activeTooltip === 'weekly' && (
            <AnimatedTooltip {...tooltipData.weekly} onClose={() => setActiveTooltip(null)} />
          )}
          <div className="flex items-center justify-between mb-4">
            <div className="p-2 rounded-xl bg-purple-500/20 group-hover:bg-purple-500/30 transition-colors">
              <BarChart3 className="w-5 h-5 text-purple-400" />
            </div>
            <div className="flex items-center gap-2">
              <InfoButton onClick={() => setActiveTooltip('weekly')} />
              {getTrendIcon(kpis.revenue_trend)}
            </div>
          </div>
          <div className="text-3xl font-bold text-white mb-1">
            <AnimatedNumber value={kpis.total_revenue_week} formatter={formatCurrencyCompact} />
          </div>
          <div className={`text-sm ${getTrendColor(kpis.revenue_trend)}`}>
            Weekly Revenue • {kpis.revenue_trend}
            <span className="text-slate-500 text-xs block mt-0.5">
              Volume: {new Intl.NumberFormat().format(kpis.total_sales_week)} units
            </span>
          </div>
        </div>

        {/* Avg Daily Sales */}
        <div className="glass rounded-2xl p-6 card-hover group relative overflow-hidden">
          {activeTooltip === 'daily' && (
            <AnimatedTooltip {...tooltipData.daily} onClose={() => setActiveTooltip(null)} />
          )}
          <div className="flex items-center justify-between mb-4">
            <div className="p-2 rounded-xl bg-amber-500/20 group-hover:bg-amber-500/30 transition-colors">
              <Calendar className="w-5 h-5 text-amber-400" />
            </div>
            <div className="flex items-center gap-2">
              <InfoButton onClick={() => setActiveTooltip('daily')} />
              <Store className="w-4 h-4 text-slate-500" />
            </div>
          </div>
          <div className="text-3xl font-bold text-white mb-1">
            {formatCurrencyCompact(kpis.average_daily_revenue)}
          </div>
          <div className="text-sm text-slate-400">
            Avg: {kpis.average_daily_sales.toFixed(0)} units/day
            <span className="text-slate-500 text-xs block mt-0.5">
              {kpis.unique_stores} stores • {kpis.unique_items} items
            </span>
          </div>
        </div>
      </div>

      {/* Secondary KPIs - Gradient Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Today's Revenue */}
        <div className="relative overflow-hidden rounded-2xl p-6 card-hover group">
          {activeTooltip === 'today' && (
            <AnimatedTooltip {...tooltipData.today} onClose={() => setActiveTooltip(null)} />
          )}
          <div className="absolute inset-0 bg-gradient-to-br from-cyan-600 to-cyan-800 opacity-90"></div>
          <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/20 to-transparent"></div>
          <div className="relative z-10">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium text-cyan-100 opacity-90">Today&apos;s Revenue</div>
              <InfoButton onClick={() => setActiveTooltip('today')} />
            </div>
            <div className="text-4xl font-bold text-white">
              <AnimatedNumber value={kpis.total_revenue_today} formatter={formatCurrency} />
            </div>
            <div className="mt-2 text-sm text-cyan-200 opacity-75">
              Volume: {new Intl.NumberFormat().format(kpis.total_sales_today)} units
            </div>
          </div>
          <div className="absolute -right-4 -bottom-4 w-24 h-24 bg-white/10 rounded-full blur-xl group-hover:scale-150 transition-transform duration-500"></div>
        </div>

        {/* Monthly Revenue */}
        <div className="relative overflow-hidden rounded-2xl p-6 card-hover group">
          {activeTooltip === 'monthly' && (
            <AnimatedTooltip {...tooltipData.monthly} onClose={() => setActiveTooltip(null)} />
          )}
          <div className="absolute inset-0 bg-gradient-to-br from-emerald-600 to-emerald-800 opacity-90"></div>
          <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/20 to-transparent"></div>
          <div className="relative z-10">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium text-emerald-100 opacity-90">Monthly Revenue</div>
              <InfoButton onClick={() => setActiveTooltip('monthly')} />
            </div>
            <div className="text-4xl font-bold text-white">
              <AnimatedNumber value={kpis.total_revenue_month} formatter={formatCurrencyCompact} />
            </div>
            <div className="mt-2 text-sm text-emerald-200 opacity-75">
              Volume: {new Intl.NumberFormat().format(kpis.total_sales_month)} units
            </div>
          </div>
          <div className="absolute -right-4 -bottom-4 w-24 h-24 bg-white/10 rounded-full blur-xl group-hover:scale-150 transition-transform duration-500"></div>
        </div>

        {/* Last Stream */}
        <div className="relative overflow-hidden rounded-2xl p-6 card-hover group">
          {activeTooltip === 'lastStream' && (
            <AnimatedTooltip {...tooltipData.lastStream} onClose={() => setActiveTooltip(null)} />
          )}
          <div className="absolute inset-0 bg-gradient-to-br from-purple-600 to-purple-800 opacity-90"></div>
          <div className="absolute inset-0 bg-gradient-to-br from-purple-500/20 to-transparent"></div>
          <div className="relative z-10">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium text-purple-100 opacity-90">Last Stream</div>
              <InfoButton onClick={() => setActiveTooltip('lastStream')} />
            </div>
            <div className="text-2xl font-bold text-white">
              {mounted && kpis.last_stream_timestamp 
                ? new Date(kpis.last_stream_timestamp).toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: true
                  })
                : kpis.last_stream_timestamp ? '--:--:--' : 'No streams yet'}
            </div>
            <div className="mt-2 text-sm text-purple-200 opacity-75">
              {mounted ? formatTimeAgo(kpis.last_stream_timestamp) : '--'}
            </div>
          </div>
          <div className="absolute -right-4 -bottom-4 w-24 h-24 bg-white/10 rounded-full blur-xl group-hover:scale-150 transition-transform duration-500"></div>
        </div>
      </div>
    </div>
  );
}

