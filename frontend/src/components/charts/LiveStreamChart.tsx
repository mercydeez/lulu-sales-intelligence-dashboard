'use client';

import { useEffect, useState, useMemo } from 'react';
import {
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  ReferenceLine,
  ComposedChart
} from 'recharts';
import { Activity, Zap, Clock, ShoppingBag, Store, TrendingUp, Package, ArrowDown, ArrowUp, RefreshCw } from 'lucide-react';
import { LiveIndicator } from '@/components/ui';
import { useEventStream } from '@/hooks/useEventStream';
import { authFetch } from '@/contexts/AuthContext';
import { shortStoreLabel } from '@/components/analytics/format';
import { CHART, gridProps, CATEGORICAL, tooltipContent, tooltipLabelStyle } from '@/lib/chart';

interface StreamingDataPoint {
  timestamp: string;
  store_name: string;
  item_name: string;
  sales: number;
  cumulative: number;
  isReturn: boolean;
  transactionType: string;
}

interface StoreItemMap {
  stores: Record<number, string>;
  items: Record<number, { name: string; category: string }>;
}

interface LiveSaleEvent {
  id: number;
  date: string;
  store_id: number;
  item_id: number;
  sales: number;
  is_streaming: boolean;
  created_at: string;
  store_name?: string;
  item_name?: string;
  category?: string;
  isReturn?: boolean;
}

// Shared categorical palette for store/category series (brand-aligned, AA on light).
const COLORS = CATEGORICAL;

export default function LiveStreamChart() {
  const [data, setData] = useState<StreamingDataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);
  const [totalStreaming, setTotalStreaming] = useState(0);
  const [totalReturns, setTotalReturns] = useState(0);
  const [returnCount, setReturnCount] = useState(0);
  const [recentSales, setRecentSales] = useState<LiveSaleEvent[]>([]);
  const [storeItemMap, setStoreItemMap] = useState<StoreItemMap>({ stores: {}, items: {} });
  const [salesByStore, setSalesByStore] = useState<Record<string, number>>({});

  useEffect(() => {
    setMounted(true);
  }, []);

  // Fetch returns summary data from API using authFetch
  useEffect(() => {
    const fetchReturnsSummary = async () => {
      try {
        const response = await authFetch('/api/analytics/returns-summary');
        if (response.ok) {
          const data = await response.json();
          setReturnCount(data.today_count || 0);
          setTotalReturns(data.today_value || 0);
        }
      } catch (error) {
        console.error('Error fetching returns summary:', error);
      }
    };

    fetchReturnsSummary();
    // Refresh returns data every 30 seconds
    const interval = setInterval(fetchReturnsSummary, 30000);
    return () => clearInterval(interval);
  }, []);

  // Fetch store and item mappings for enriching live data using authFetch
  useEffect(() => {
    const fetchMappings = async () => {
      try {
        const [storesRes, itemsRes] = await Promise.all([
          authFetch('/api/analytics/stores'),
          authFetch('/api/analytics/top-items?limit=50')
        ]);

        if (storesRes.ok) {
          const storesData = await storesRes.json();
          const storesMap: Record<number, string> = {};
          storesData.data?.forEach((s: { store_id: number; store_name: string }) => {
            storesMap[s.store_id] = s.store_name;
          });
          setStoreItemMap(prev => ({ ...prev, stores: storesMap }));
        }

        if (itemsRes.ok) {
          const itemsData = await itemsRes.json();
          const itemsMap: Record<number, { name: string; category: string }> = {};
          itemsData.data?.forEach((i: { item_id: number; item_name: string; category: string }) => {
            itemsMap[i.item_id] = { name: i.item_name, category: i.category };
          });
          setStoreItemMap(prev => ({ ...prev, items: itemsMap }));
        }
      } catch (error) {
        console.error('Error fetching mappings:', error);
      }
    };
    fetchMappings();
  }, []);

  // Fetch initial streaming data using authFetch
  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await authFetch('/api/analytics/streaming-trend');
        if (!response.ok) throw new Error('Failed to fetch streaming data');
        const result = await response.json();
        setData(result.data || []);
        setTotalStreaming(result.total_streaming || 0);

        // Calculate sales by store and category from historical data
        const byStore: Record<string, number> = {};
        result.data?.forEach((point: StreamingDataPoint) => {
          byStore[point.store_name] = (byStore[point.store_name] || 0) + point.sales;
        });
        setSalesByStore(byStore);
      } catch (error) {
        console.error('Error fetching streaming data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  // Connect to SSE for real-time updates using useEventStream hook
  const eventHandlers = useMemo(() => ({
    sales: (saleData: any) => {
      // Detect if this is a return (negative sales value)
      const isReturn = saleData.sales < 0;

      // Enrich with store/item names
      const storeName = storeItemMap.stores[saleData.store_id] || `Store ${saleData.store_id}`;
      const itemInfo = storeItemMap.items[saleData.item_id] || { name: `Item ${saleData.item_id}`, category: 'General' };

      const enrichedSale: LiveSaleEvent = {
        ...saleData,
        store_name: storeName,
        item_name: itemInfo.name,
        category: itemInfo.category,
        isReturn
      };

      // Add to recent sales (keep last 10)
      setRecentSales(prev => [enrichedSale, ...prev.slice(0, 9)]);

      // Update totals (returns reduce the total)
      setTotalStreaming(prev => prev + saleData.sales);

      // Track returns separately
      if (isReturn) {
        setTotalReturns(prev => prev + Math.abs(saleData.sales));
        setReturnCount(prev => prev + 1);
      }

      // Update sales by store
      setSalesByStore(prev => ({
        ...prev,
        [storeName]: (prev[storeName] || 0) + saleData.sales
      }));

      // Update chart data with return information
      setData(prev => {
        const lastCumulative = prev.length > 0 ? prev[prev.length - 1].cumulative : 0;
        const newPoint: StreamingDataPoint = {
          timestamp: saleData.created_at,
          store_name: storeName,
          item_name: itemInfo.name,
          sales: saleData.sales,
          cumulative: lastCumulative + saleData.sales,
          isReturn,
          transactionType: isReturn ? 'RETURN' : 'SALE'
        };
        return [...prev.slice(-49), newPoint]; // Keep last 50 points
      });
    }
  }), [storeItemMap]);

  const hasMappings = Object.keys(storeItemMap.stores).length > 0;
  useEventStream(hasMappings ? '/stream/sales' : null, { eventHandlers });

  const formatTime = (timestamp: string) => {
    if (!mounted || !timestamp) return '--:--';
    try {
      // Handle various timestamp formats
      let dateStr = timestamp;
      // If it doesn't have timezone info, assume UTC
      if (!dateStr.includes('Z') && !dateStr.includes('+')) {
        dateStr = dateStr + 'Z';
      }
      const date = new Date(dateStr);
      if (isNaN(date.getTime())) return '--:--';
      return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    } catch {
      return '--:--';
    }
  };

  const formatNumber = (value: number) => {
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return value.toString();
  };

  const getTimeSince = (timestamp: string) => {
    if (!mounted || !timestamp) return 'just now';
    try {
      let dateStr = timestamp;
      if (!dateStr.includes('Z') && !dateStr.includes('+')) {
        dateStr = dateStr + 'Z';
      }
      const date = new Date(dateStr);
      if (isNaN(date.getTime())) return 'just now';
      const seconds = Math.floor((new Date().getTime() - date.getTime()) / 1000);
      if (seconds < 60) return `${seconds}s ago`;
      if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
      return `${Math.floor(seconds / 3600)}h ago`;
    } catch {
      return 'just now';
    }
  };

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: StreamingDataPoint }> }) => {
    if (active && payload && payload.length) {
      const point = payload[0].payload;
      const isReturn = point.isReturn || point.sales < 0;

      return (
        <div className={`glass-strong rounded-xl p-3 border shadow-elevated min-w-[200px] ${
          isReturn ? 'border-rose-200 bg-rose-50' : 'border-line'
        }`}>
          {/* Transaction Type Badge */}
          <div className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-bold mb-2 ${
            isReturn
              ? 'bg-rose-100 text-rose-700'
              : 'bg-emerald-100 text-emerald-700'
          }`}>
            {isReturn ? (
              <>
                <RefreshCw className="w-3 h-3" />
                RETURN
              </>
            ) : (
              <>
                <ArrowUp className="w-3 h-3" />
                SALE
              </>
            )}
          </div>

          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-3 h-3 text-teal-600" />
            <p className="text-ink font-semibold text-sm">{mounted ? formatTime(point.timestamp) : '--'}</p>
          </div>
          <div className="space-y-1 mb-3">
            <div className="flex items-center gap-2">
              <Store className="w-3 h-3 text-violet-600" />
              <p className="text-ink-soft text-xs">{point.store_name}</p>
            </div>
            <div className="flex items-center gap-2">
              <Package className="w-3 h-3 text-amber-600" />
              <p className="text-ink-soft text-xs">{point.item_name}</p>
            </div>
          </div>
          <div className="flex items-center justify-between pt-2 border-t border-line">
            <div>
              <p className="text-xs text-ink-muted">{isReturn ? 'Returned' : 'Sold'}</p>
              <p className={`font-bold text-lg ${isReturn ? 'text-rose-600' : 'text-teal-600'}`}>
                {isReturn ? `${Math.abs(point.sales)}` : point.sales}
                {isReturn && <span className="text-xs ms-1">↓</span>}
              </p>
            </div>
            <div className="text-end">
              <p className="text-xs text-ink-muted">Cumulative</p>
              <p className="text-emerald-600 font-bold text-lg">{formatNumber(point.cumulative)}</p>
            </div>
          </div>
        </div>
      );
    }
    return null;
  };

  // Prepare store distribution data for mini bar chart
  const storeChartData = Object.entries(salesByStore)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([name, sales], index) => ({ name: shortStoreLabel(name), fullName: name, sales, color: COLORS[index % COLORS.length] }));

  if (loading) {
    return (
      <div className="glass rounded-2xl p-6 h-[500px] flex items-center justify-center">
        <div className="shimmer w-full h-full rounded-xl"></div>
      </div>
    );
  }

  return (
    <div className="glass rounded-2xl p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-teal-50 ring-1 ring-teal-100">
            <Activity className="w-5 h-5 text-teal-600" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-ink">Live Streaming Sales</h3>
            <p className="text-xs text-ink-muted">Real-time sales &amp; returns with fluctuations</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {/* Net Total */}
          <div className="text-end">
            <div className={`text-2xl font-bold ${totalStreaming >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
              {formatNumber(totalStreaming)}
            </div>
            <div className="text-xs text-ink-muted">Net Total</div>
          </div>
          {/* Returns Counter */}
          {returnCount > 0 && (
            <div className="text-end px-3 py-1 bg-rose-50 rounded-lg border border-rose-200">
              <div className="flex items-center gap-1 text-rose-600 text-sm font-bold">
                <RefreshCw className="w-3 h-3" />
                {returnCount}
              </div>
              <div className="text-xs text-rose-600/70">Returns</div>
            </div>
          )}
          {/* Canonical teal live pulse (rose = danger, not "live") */}
          <LiveIndicator />
        </div>
      </div>

      {/* Main Chart - Shows cumulative with fluctuations */}
      <div className="h-[220px]">
        {data.length === 0 ? (
          <div className="h-full flex items-center justify-center text-ink-muted">
            <div className="text-center">
              <Zap className="w-8 h-8 mx-auto mb-2 text-ink-muted/40" />
              <p>Waiting for streaming data...</p>
              <p className="text-xs text-ink-muted/70 mt-1">Data will appear as sales stream in</p>
            </div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="cumulativeGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.emerald} stopOpacity={0.4} />
                  <stop offset="95%" stopColor={CHART.emerald} stopOpacity={0} />
                </linearGradient>
                <linearGradient id="positiveGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.teal} stopOpacity={0.8} />
                  <stop offset="95%" stopColor={CHART.teal} stopOpacity={0.3} />
                </linearGradient>
                <linearGradient id="negativeGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={CHART.coral} stopOpacity={0.8} />
                  <stop offset="95%" stopColor={CHART.coral} stopOpacity={0.3} />
                </linearGradient>
              </defs>
              <CartesianGrid {...gridProps} />
              <XAxis
                dataKey="timestamp"
                tickFormatter={formatTime}
                stroke={CHART.axis}
                fontSize={10}
                tickLine={false}
                axisLine={{ stroke: CHART.grid }}
                interval="preserveStartEnd"
              />
              <YAxis
                yAxisId="cumulative"
                orientation="left"
                stroke={CHART.axis}
                fontSize={11}
                tickFormatter={formatNumber}
                tickLine={false}
                axisLine={{ stroke: CHART.grid }}
              />
              <YAxis
                yAxisId="sales"
                orientation="right"
                stroke={CHART.axis}
                fontSize={10}
                tickLine={false}
                axisLine={false}
                domain={['dataMin - 10', 'dataMax + 10']}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine yAxisId="sales" y={0} stroke={CHART.grid} strokeDasharray="3 3" />
              {/* Cumulative line - shows overall trend with dips */}
              <Area
                yAxisId="cumulative"
                type="monotone"
                dataKey="cumulative"
                stroke={CHART.emerald}
                strokeWidth={2}
                fill="url(#cumulativeGradient)"
                dot={false}
                activeDot={{ r: 6, fill: CHART.emerald, stroke: 'var(--bg-card)', strokeWidth: 2 }}
              />
              {/* Sales bars - shows individual transactions with red for returns */}
              <Bar
                yAxisId="sales"
                dataKey="sales"
                maxBarSize={20}
              >
                {data.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.sales < 0 ? CHART.coral : CHART.teal}
                    fillOpacity={0.7}
                  />
                ))}
              </Bar>
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-3 mt-4 pt-4 border-t border-line">
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <TrendingUp className="w-4 h-4 text-teal-600 mx-auto mb-1" />
          <div className="text-lg font-bold text-ink">{data.length}</div>
          <div className="text-xs text-ink-muted">Transactions</div>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <Store className="w-4 h-4 text-violet-600 mx-auto mb-1" />
          <div className="text-lg font-bold text-ink">{Object.keys(salesByStore).length}</div>
          <div className="text-xs text-ink-muted">Active Stores</div>
        </div>
        <div className="bg-surface-2 rounded-lg p-3 text-center">
          <ShoppingBag className="w-4 h-4 text-amber-600 mx-auto mb-1" />
          <div className="text-lg font-bold text-ink">{data.length > 0 ? Math.round(totalStreaming / data.length) : 0}</div>
          <div className="text-xs text-ink-muted">Avg per Txn</div>
        </div>
        <div className={`rounded-lg p-3 text-center ${returnCount > 0 ? 'bg-rose-50 border border-rose-200' : 'bg-surface-2'}`}>
          <RefreshCw className={`w-4 h-4 mx-auto mb-1 ${returnCount > 0 ? 'text-rose-600' : 'text-ink-muted'}`} />
          <div className={`text-lg font-bold ${returnCount > 0 ? 'text-rose-600' : 'text-ink-muted'}`}>{returnCount}</div>
          <div className="text-xs text-ink-muted">Returns</div>
        </div>
      </div>

      {/* Live Feed - Recent Sales with Details */}
      <div className="mt-4 pt-4 border-t border-line">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-rose-600" />
            <span className="text-sm font-medium text-ink">Live Sales Feed</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 text-xs">
              <span className="w-2 h-2 rounded-full bg-teal-500"></span>
              <span className="text-ink-muted">Sale</span>
            </span>
            <span className="flex items-center gap-1 text-xs">
              <span className="w-2 h-2 rounded-full bg-rose-400"></span>
              <span className="text-ink-muted">Return</span>
            </span>
          </div>
        </div>

        <div className="space-y-2 max-h-[200px] overflow-y-auto pe-2 custom-scrollbar">
          {(recentSales.length > 0 ? recentSales : data.slice(-5).reverse()).map((sale, index) => {
            const isRecentSale = 'category' in sale;
            const saleItem = isRecentSale ? sale as LiveSaleEvent : null;
            const dataPoint = !isRecentSale ? sale as StreamingDataPoint : null;
            const salesValue = saleItem?.sales ?? dataPoint?.sales ?? 0;
            const isReturnItem = salesValue < 0 || saleItem?.isReturn || dataPoint?.isReturn;

            return (
              <div
                key={saleItem?.id || index}
                className={`flex items-center justify-between p-3 rounded-lg border transition-all duration-300 ${
                  isReturnItem
                    ? 'bg-rose-50 border-rose-200'
                    : index === 0 && recentSales.length > 0
                    ? 'bg-emerald-50 border-emerald-200 animate-pulse'
                    : 'bg-surface-2 border-line'
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                    isReturnItem
                      ? 'bg-rose-100'
                      : index === 0 && recentSales.length > 0
                      ? 'bg-emerald-100'
                      : 'bg-surface-3'
                  }`}>
                    {isReturnItem ? (
                      <RefreshCw className="w-5 h-5 text-rose-600" />
                    ) : (
                      <ShoppingBag className={`w-5 h-5 ${index === 0 && recentSales.length > 0 ? 'text-emerald-600' : 'text-ink-muted'}`} />
                    )}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-ink">
                        {saleItem?.item_name || dataPoint?.item_name || 'Unknown Item'}
                      </span>
                      {isReturnItem && (
                        <span className="px-1.5 py-0.5 text-[10px] rounded bg-rose-100 text-rose-700 font-semibold">
                          RETURN
                        </span>
                      )}
                      {saleItem?.category && !isReturnItem && (
                        <span className="px-1.5 py-0.5 text-[10px] rounded bg-violet-100 text-violet-700">
                          {saleItem.category}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-ink-muted">
                      <Store className="w-3 h-3" />
                      <span>{saleItem?.store_name || dataPoint?.store_name || 'Unknown Store'}</span>
                      <span>•</span>
                      <Clock className="w-3 h-3" />
                      <span>{getTimeSince(saleItem?.created_at || dataPoint?.timestamp || '')}</span>
                    </div>
                  </div>
                </div>
                <div className="text-end">
                  <div className={`text-lg font-bold flex items-center gap-1 ${isReturnItem ? 'text-rose-600' : 'text-teal-600'}`}>
                    {isReturnItem && <ArrowDown className="w-4 h-4" />}
                    {!isReturnItem && <ArrowUp className="w-4 h-4" />}
                    {Math.abs(salesValue)}
                  </div>
                  <div className="text-xs text-ink-muted">Qty</div>
                </div>
              </div>
            );
          })}

          {recentSales.length === 0 && data.length === 0 && (
            <div className="text-center py-8 text-ink-muted">
              <Zap className="w-6 h-6 mx-auto mb-2 text-ink-muted/40" />
              <p className="text-sm">No sales yet today</p>
              <p className="text-xs mt-1">Sales will appear here as they stream in</p>
            </div>
          )}
        </div>
      </div>

      {/* Store Distribution Mini Chart */}
      {storeChartData.length > 0 && (
        <div className="mt-4 pt-4 border-t border-line">
          <div className="flex items-center gap-2 mb-3">
            <Store className="w-4 h-4 text-violet-600" />
            <span className="text-sm font-medium text-ink">Sales by Store (Today)</span>
          </div>
          <div className="h-[100px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={storeChartData} layout="vertical" margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                <XAxis type="number" hide />
                <YAxis
                  type="category"
                  dataKey="name"
                  axisLine={false}
                  tickLine={false}
                  fontSize={11}
                  stroke={CHART.axis}
                  width={96}
                />
                <Tooltip
                  formatter={(value: number) => [formatNumber(value), 'Sales']}
                  labelFormatter={(label: string) => storeChartData.find(s => s.name === label)?.fullName || label}
                  contentStyle={tooltipContent}
                  labelStyle={tooltipLabelStyle}
                />
                <Bar dataKey="sales" radius={[0, 4, 4, 0]}>
                  {storeChartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
