'use client';

import { useEffect, useState } from 'react';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip
} from 'recharts';
import { RotateCcw } from 'lucide-react';
import { authFetch } from '@/contexts/AuthContext';
import { CATEGORICAL as COLORS } from '@/lib/chart';

interface ReturnCategoryData {
  category: string;
  count: number;
  value: number;
  percentage: number;
}

export default function ReturnsByCategoryChart() {
  const [data, setData] = useState<ReturnCategoryData[]>([]);
  const [loading, setLoading] = useState(true);
  const [totalReturns, setTotalReturns] = useState(0);
  const [totalValue, setTotalValue] = useState(0);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await authFetch('/api/analytics/returns-by-category');
        if (!response.ok) throw new Error('Failed to fetch returns data');
        const result = await response.json();

        // Calculate percentages
        const total = result.data.reduce((sum: number, item: ReturnCategoryData) => sum + item.count, 0);
        const dataWithPercentage = result.data.map((item: ReturnCategoryData) => ({
          ...item,
          percentage: total > 0 ? (item.count / total) * 100 : 0
        }));

        setData(dataWithPercentage);
        setTotalReturns(result.total_count || total);
        setTotalValue(result.total_value || 0);
      } catch (error) {
        console.error('Error fetching returns data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();

    // Refresh every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  const formatNumber = (value: number) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return value.toString();
  };

  const onPieEnter = (_: unknown, index: number) => {
    setActiveIndex(index);
  };

  const onPieLeave = () => {
    setActiveIndex(null);
  };

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: ReturnCategoryData }> }) => {
    if (active && payload && payload.length) {
      const category = payload[0].payload;
      return (
        <div className="glass-strong rounded-lg p-3 border border-rose-200 shadow-lg">
          <p className="text-ink font-semibold">{category.category}</p>
          <p className="text-rose-600 font-medium">{category.count} Returns</p>
          <p className="text-amber-600">{formatNumber(category.value)} Units Returned</p>
          <p className="text-ink-muted">{category.percentage.toFixed(1)}% of total returns</p>
        </div>
      );
    }
    return null;
  };

  const renderCustomizedLabel = ({
    cx,
    cy,
    midAngle,
    innerRadius,
    outerRadius,
    percent,
  }: {
    cx: number;
    cy: number;
    midAngle: number;
    innerRadius: number;
    outerRadius: number;
    percent: number;
    index: number;
  }) => {
    if (percent < 0.05) return null; // Don't show labels for small slices

    const RADIAN = Math.PI / 180;
    const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
    const x = cx + radius * Math.cos(-midAngle * RADIAN);
    const y = cy + radius * Math.sin(-midAngle * RADIAN);

    return (
      <text
        x={x}
        y={y}
        fill="white"
        textAnchor="middle"
        dominantBaseline="central"
        className="text-xs font-semibold"
        style={{ textShadow: '0 1px 2px rgba(0,0,0,0.45)' }}
      >
        {`${(percent * 100).toFixed(0)}%`}
      </text>
    );
  };

  if (loading) {
    return (
      <div className="glass rounded-xl p-6 h-[400px] flex items-center justify-center">
        <div className="animate-pulse flex flex-col items-center">
          <div className="w-32 h-32 rounded-full bg-coral-100"></div>
          <div className="mt-4 h-4 bg-coral-100 rounded w-32"></div>
        </div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="glass rounded-xl p-6 h-[400px] flex items-center justify-center">
        <div className="text-center">
          <RotateCcw className="w-12 h-12 text-ink-muted/60 mx-auto mb-3" />
          <p className="text-ink-soft">No return data available</p>
          <p className="text-ink-muted text-sm">Returns will appear here as they occur</p>
        </div>
      </div>
    );
  }

  return (
    <div className="glass rounded-xl p-6 relative">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-rose-100 rounded-lg">
            <RotateCcw className="w-5 h-5 text-rose-600" />
          </div>
          <div>
            <h3 className="text-ink font-semibold">Returns by Category</h3>
            <p className="text-ink-muted text-sm">Product category breakdown</p>
          </div>
        </div>
        <div className="text-end">
          <p className="text-2xl font-bold text-rose-600">{totalReturns}</p>
          <p className="text-ink-muted text-xs">Total Returns</p>
        </div>
      </div>

      {/* Chart */}
      <div className="h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              labelLine={false}
              label={renderCustomizedLabel}
              innerRadius={60}
              outerRadius={100}
              paddingAngle={2}
              dataKey="count"
              onMouseEnter={onPieEnter}
              onMouseLeave={onPieLeave}
            >
              {data.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={COLORS[index % COLORS.length]}
                  stroke={activeIndex === index ? 'var(--text-primary)' : 'transparent'}
                  strokeWidth={activeIndex === index ? 2 : 0}
                  style={{
                    filter: activeIndex === index ? 'brightness(1.1)' : 'none',
                    transition: 'all 0.3s ease'
                  }}
                />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Center Stats — scoped to this card via the relative parent */}
      <div className="absolute inset-x-0 top-[52%] flex items-center justify-center pointer-events-none">
        <div className="text-center">
          <p className="text-3xl font-bold text-ink">{formatNumber(totalValue)}</p>
          <p className="text-ink-muted text-xs">Units (Qty) Returned</p>
        </div>
      </div>

      {/* Legend */}
      <div className="mt-4 grid grid-cols-2 gap-2 max-h-[120px] overflow-y-auto">
        {data.slice(0, 8).map((item: ReturnCategoryData, index: number) => (
          <div
            key={item.category}
            className="flex items-center gap-2 p-2 rounded-lg hover:bg-surface-2 transition-colors cursor-pointer"
            onMouseEnter={() => setActiveIndex(index)}
            onMouseLeave={() => setActiveIndex(null)}
          >
            <div
              className="w-3 h-3 rounded-full flex-shrink-0"
              style={{ backgroundColor: COLORS[index % COLORS.length] }}
            />
            <div className="min-w-0 flex-1">
              <p className="text-ink text-sm truncate">{item.category}</p>
              <p className="text-ink-muted text-xs">{item.count} returns</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
