'use client';

import { useEffect, useState } from 'react';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip
} from 'recharts';
import { Layers } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface CategoryData {
  category: string;
  total_sales: number;
  percentage: number;
}

const COLORS = [
  '#10b981', // emerald
  '#06b6d4', // cyan
  '#8b5cf6', // purple
  '#f59e0b', // amber
  '#ef4444', // red
  '#ec4899', // pink
  '#6366f1', // indigo
  '#14b8a6', // teal
  '#f97316', // orange
  '#84cc16', // lime
  '#22d3ee', // cyan-light
  '#a78bfa', // violet
];

export default function CategoryBreakdownChart() {
  const [data, setData] = useState<CategoryData[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(`${API_URL}/api/analytics/categories`);
        if (!response.ok) throw new Error('Failed to fetch category data');
        const result = await response.json();
        setData(result.data);
        setTotal(result.total);
      } catch (error) {
        console.error('Error fetching category data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
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

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: CategoryData }> }) => {
    if (active && payload && payload.length) {
      const category = payload[0].payload;
      return (
        <div className="glass rounded-lg p-3 border border-slate-600">
          <p className="text-white font-semibold">{category.category}</p>
          <p className="text-emerald-400">{formatNumber(category.total_sales)} Units</p>
          <p className="text-slate-400">{category.percentage.toFixed(1)}% of total</p>
        </div>
      );
    }
    return null;
  };

  if (loading) {
    return (
      <div className="glass rounded-2xl p-6 h-[400px] flex items-center justify-center">
        <div className="shimmer w-full h-full rounded-xl"></div>
      </div>
    );
  }

  return (
    <div className="glass rounded-2xl p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-emerald-500/20">
            <Layers className="w-5 h-5 text-emerald-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Category Analysis</h3>
            <p className="text-xs text-slate-400">Sales breakdown by product category</p>
          </div>
        </div>
      </div>

      {/* Chart and Legend Side by Side */}
      <div className="flex items-center">
        {/* Donut Chart */}
        <div className="h-[250px] w-[250px] flex-shrink-0 relative">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={85}
                paddingAngle={3}
                dataKey="total_sales"
                nameKey="category"
                onMouseEnter={onPieEnter}
                onMouseLeave={onPieLeave}
              >
                {data.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`} 
                    fill={COLORS[index % COLORS.length]}
                    stroke="#0f172a"
                    strokeWidth={2}
                    opacity={activeIndex === null || activeIndex === index ? 1 : 0.5}
                  />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
          {/* Center stats */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center">
              <div className="text-xl font-bold text-white">{data.length}</div>
              <div className="text-xs text-slate-400">Categories</div>
            </div>
          </div>
        </div>

        {/* Legend */}
        <div className="flex-1 pl-4 max-h-[260px] overflow-y-auto">
          <div className="space-y-2">
            {data.map((category, index) => (
              <div 
                key={category.category}
                className={`flex items-center justify-between px-3 py-2 rounded-lg transition-all ${
                  activeIndex === index 
                    ? 'bg-slate-700/70 scale-[1.02]' 
                    : 'bg-slate-800/30 hover:bg-slate-700/50'
                }`}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseLeave={() => setActiveIndex(null)}
              >
                <div className="flex items-center gap-2">
                  <div 
                    className="w-3 h-3 rounded-full flex-shrink-0" 
                    style={{ backgroundColor: COLORS[index % COLORS.length] }}
                  />
                  <span className="text-sm text-white">{category.category}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-slate-400">{formatNumber(category.total_sales)}</span>
                  <span 
                    className="text-xs font-semibold px-2 py-0.5 rounded"
                    style={{ 
                      backgroundColor: `${COLORS[index % COLORS.length]}20`,
                      color: COLORS[index % COLORS.length]
                    }}
                  >
                    {category.percentage.toFixed(1)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
