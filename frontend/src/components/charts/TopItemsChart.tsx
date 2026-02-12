'use client';

import { useEffect, useState } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell
} from 'recharts';
import { Award, TrendingUp } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ItemData {
  item_id: number;
  item_name: string;
  category: string;
  total_sales: number;
}

const COLORS = [
  '#06b6d4', // cyan
  '#0ea5e9', // sky
  '#3b82f6', // blue
  '#6366f1', // indigo
  '#8b5cf6', // violet
  '#a855f7', // purple
  '#d946ef', // fuchsia
  '#ec4899', // pink
  '#f43f5e', // rose
  '#ef4444', // red
];

export default function TopItemsChart() {
  const [data, setData] = useState<ItemData[]>([]);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(`${API_URL}/api/analytics/top-items?limit=10`);
        if (!response.ok) throw new Error('Failed to fetch top items');
        const result = await response.json();
        setData(result.data);
      } catch (error) {
        console.error('Error fetching top items:', error);
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

  const shortenName = (name: string) => {
    if (name.length > 20) {
      return name.substring(0, 18) + '...';
    }
    return name;
  };

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: ItemData }> }) => {
    if (active && payload && payload.length) {
      const item = payload[0].payload;
      return (
        <div className="glass rounded-lg p-3 border border-slate-600">
          <p className="text-white font-semibold text-sm">{item.item_name}</p>
          <p className="text-slate-400 text-xs mb-1">{item.category}</p>
          <p className="text-cyan-400 font-bold">{formatNumber(item.total_sales)} Units</p>
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
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-amber-500/20">
            <Award className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Top Selling Products</h3>
            <p className="text-xs text-slate-400">Best performing items by volume</p>
          </div>
        </div>
        {data.length > 0 && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-500/20">
            <TrendingUp className="w-4 h-4 text-emerald-400" />
            <span className="text-sm text-emerald-400 font-semibold">
              #{1} {shortenName(data[0]?.item_name || '')}
            </span>
          </div>
        )}
      </div>

      {/* Chart */}
      <div className="h-[300px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 0, right: 30, left: 0, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" horizontal={true} vertical={false} />
            <XAxis 
              type="number"
              stroke="#64748b"
              fontSize={12}
              tickFormatter={formatNumber}
              tickLine={false}
              axisLine={{ stroke: '#334155' }}
            />
            <YAxis 
              type="category"
              dataKey="item_name"
              stroke="#64748b"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              width={150}
              tickFormatter={shortenName}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(100, 116, 139, 0.1)' }} />
            <Bar 
              dataKey="total_sales" 
              radius={[0, 4, 4, 0]}
              barSize={24}
            >
              {data.map((entry, index) => (
                <Cell 
                  key={`cell-${index}`} 
                  fill={COLORS[index % COLORS.length]}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Category breakdown */}
      <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-slate-700/50">
        {Array.from(new Set(data.map(d => d.category))).slice(0, 5).map((category, index) => (
          <span 
            key={category}
            className="px-3 py-1 rounded-full text-xs font-medium"
            style={{ 
              backgroundColor: `${COLORS[index % COLORS.length]}20`,
              color: COLORS[index % COLORS.length]
            }}
          >
            {category}
          </span>
        ))}
      </div>
    </div>
  );
}
