'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  LineChart, Line, BarChart, Bar, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { ChartFrame } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import { PerformanceChartData } from './types';

interface EmployeePerformanceChartProps {
  employeeId?: number;
  role?: string;
  storeId?: number;
  chartType?: 'line' | 'bar' | 'radar';
  title?: string;
}

const CHART = { coral: '#ff6b5c', teal: '#2dd4bf', violet: '#8b5cf6', amber: '#fbbf24', grid: 'rgba(30,27,46,0.08)', axis: '#8b8699' };
const tooltipStyle = { backgroundColor: '#fff', border: '1px solid #f1d9d2', borderRadius: '12px', color: '#1e1b2e' };

const METRICS = [
  { key: 'performance_score', label: 'Performance', color: CHART.coral },
  { key: 'sales', label: 'Sales', color: CHART.teal },
  { key: 'customer_rating', label: 'Rating', color: CHART.amber },
  { key: 'attendance', label: 'Attendance', color: CHART.violet },
] as const;

export function EmployeePerformanceChart({
  employeeId, role, storeId, chartType = 'line', title = 'Employee Performance',
}: EmployeePerformanceChartProps) {
  const { authFetch } = useAuth();
  const [data, setData] = useState<PerformanceChartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [metric, setMetric] = useState<string>('performance_score');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    const params = new URLSearchParams();
    if (employeeId) params.append('employee_id', String(employeeId));
    if (role) params.append('role', role);
    if (storeId) params.append('store_id', String(storeId));
    params.append('periods', '6');

    authFetch(`/api/employees/employees/performance/chart-data?${params}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('failed'))))
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [employeeId, role, storeId, authFetch]);

  const rows = useMemo(() => {
    if (!data) return [];
    return data.labels.map((name, i) => ({
      name,
      performance_score: data.datasets.performance_score[i] ?? 0,
      sales: data.datasets.sales[i] ?? 0,
      customer_rating: data.datasets.customer_rating[i] ?? 0,
      attendance: data.datasets.attendance[i] ?? 0,
    }));
  }, [data]);

  // Radar compares three 0–100 comparable metrics on the latest period.
  const radarData = useMemo(() => {
    if (!rows.length) return [];
    const last = rows[rows.length - 1];
    return [
      { metric: 'Performance', value: Math.round(last.performance_score) },
      { metric: 'Attendance', value: Math.round(last.attendance) },
      { metric: 'Rating', value: Math.round(last.customer_rating * 20) },
    ];
  }, [rows]);

  const active = METRICS.find((m) => m.key === metric) ?? METRICS[0];
  const isEmpty = !loading && (error || rows.length === 0);

  const metricToggle =
    chartType !== 'radar' ? (
      <div className="flex flex-wrap gap-1">
        {METRICS.map((m) => (
          <button
            key={m.key}
            type="button"
            onClick={() => setMetric(m.key)}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
              metric === m.key ? 'bg-coral-100 text-coral-600' : 'text-ink-muted hover:bg-coral-50'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
    ) : undefined;

  return (
    <ChartFrame title={title} height={300} loading={loading} empty={isEmpty} actions={metricToggle}>
      <ResponsiveContainer width="100%" height="100%">
        {chartType === 'radar' ? (
          <RadarChart data={radarData} outerRadius="70%">
            <PolarGrid stroke={CHART.grid} />
            <PolarAngleAxis dataKey="metric" tick={{ fill: CHART.axis, fontSize: 12 }} />
            <PolarRadiusAxis domain={[0, 100]} tick={{ fill: CHART.axis, fontSize: 10 }} />
            <Radar dataKey="value" stroke={CHART.coral} fill={CHART.coral} fillOpacity={0.4} />
            <Tooltip contentStyle={tooltipStyle} />
          </RadarChart>
        ) : chartType === 'bar' ? (
          <BarChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="name" stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} />
            <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,107,92,0.06)' }} />
            <Bar dataKey={active.key} name={active.label} fill={active.color} radius={[6, 6, 0, 0]} maxBarSize={48} />
          </BarChart>
        ) : (
          <LineChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="name" stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} />
            <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={{ stroke: CHART.grid }} />
            <Tooltip contentStyle={tooltipStyle} />
            <Line type="monotone" dataKey={active.key} name={active.label} stroke={active.color} strokeWidth={2.5} dot={{ fill: active.color, r: 3 }} />
          </LineChart>
        )}
      </ResponsiveContainer>
    </ChartFrame>
  );
}
