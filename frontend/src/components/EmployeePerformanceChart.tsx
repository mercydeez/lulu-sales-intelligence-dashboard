'use client';

import React, { useState, useEffect } from 'react';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, RadarChart, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis, Radar, PieChart, Pie, Cell
} from 'recharts';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface PerformanceData {
  labels: string[];
  datasets: {
    performance_score: number[];
    sales: number[];
    customer_rating: number[];
    attendance: number[];
    transactions: number[];
  };
}

interface EmployeePerformanceChartProps {
  employeeId?: number;
  role?: string;
  storeId?: number;
  chartType?: 'line' | 'bar' | 'radar';
  title?: string;
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'];

export default function EmployeePerformanceChart({
  employeeId,
  role,
  storeId,
  chartType = 'line',
  title = 'Employee Performance Trends'
}: EmployeePerformanceChartProps) {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedMetric, setSelectedMetric] = useState<string>('performance_score');

  useEffect(() => {
    fetchPerformanceData();
  }, [employeeId, role, storeId]);

  const fetchPerformanceData = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (employeeId) params.append('employee_id', employeeId.toString());
      if (role) params.append('role', role);
      if (storeId) params.append('store_id', storeId.toString());
      params.append('periods', '6');

      const response = await fetch(
        `${API_URL}/api/employees/employees/performance/chart-data?${params}`
      );

      if (!response.ok) throw new Error('Failed to fetch performance data');
      
      const result = await response.json();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-4"></div>
          <div className="h-64 bg-gray-200 dark:bg-gray-700 rounded"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <div className="text-red-500 text-center">
          <p>Error loading performance data</p>
          <p className="text-sm text-gray-500">{error}</p>
        </div>
      </div>
    );
  }

  if (!data || data.labels.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <div className="text-gray-500 text-center">
          <p>No performance data available</p>
        </div>
      </div>
    );
  }

  // Transform data for charts
  const chartData = data.labels.map((label, index) => ({
    name: label,
    performance_score: data.datasets.performance_score[index],
    sales: data.datasets.sales[index],
    customer_rating: data.datasets.customer_rating[index] * 20, // Scale to 100
    attendance: data.datasets.attendance[index],
    transactions: data.datasets.transactions[index]
  }));

  // Radar chart data
  const latestData = chartData[chartData.length - 1];
  const radarData = [
    { metric: 'Performance', value: latestData?.performance_score || 0, fullMark: 100 },
    { metric: 'Sales', value: Math.min((latestData?.sales || 0) / 1000, 100), fullMark: 100 },
    { metric: 'Rating', value: latestData?.customer_rating || 0, fullMark: 100 },
    { metric: 'Attendance', value: latestData?.attendance || 0, fullMark: 100 },
  ];

  const metrics = [
    { key: 'performance_score', label: 'Performance Score', color: '#3b82f6' },
    { key: 'sales', label: 'Sales (AED)', color: '#10b981' },
    { key: 'customer_rating', label: 'Customer Rating', color: '#f59e0b' },
    { key: 'attendance', label: 'Attendance %', color: '#8b5cf6' },
  ];

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-lg font-semibold text-gray-800 dark:text-white">{title}</h3>
        <div className="flex gap-2">
          {metrics.map((m) => (
            <button
              key={m.key}
              onClick={() => setSelectedMetric(m.key)}
              className={`px-3 py-1 text-xs rounded-full transition-colors ${
                selectedMetric === m.key
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {chartType === 'line' && (
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
            <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
            <YAxis stroke="#9ca3af" fontSize={12} />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1f2937',
                border: 'none',
                borderRadius: '8px',
                color: '#f9fafb'
              }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey={selectedMetric}
              stroke={metrics.find(m => m.key === selectedMetric)?.color || '#3b82f6'}
              strokeWidth={3}
              dot={{ fill: metrics.find(m => m.key === selectedMetric)?.color || '#3b82f6', r: 4 }}
              activeDot={{ r: 6 }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}

      {chartType === 'bar' && (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
            <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
            <YAxis stroke="#9ca3af" fontSize={12} />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1f2937',
                border: 'none',
                borderRadius: '8px',
                color: '#f9fafb'
              }}
            />
            <Legend />
            <Bar
              dataKey={selectedMetric}
              fill={metrics.find(m => m.key === selectedMetric)?.color || '#3b82f6'}
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      )}

      {chartType === 'radar' && (
        <ResponsiveContainer width="100%" height={300}>
          <RadarChart data={radarData}>
            <PolarGrid stroke="#374151" />
            <PolarAngleAxis dataKey="metric" stroke="#9ca3af" fontSize={12} />
            <PolarRadiusAxis angle={30} domain={[0, 100]} stroke="#9ca3af" fontSize={10} />
            <Radar
              name="Current Period"
              dataKey="value"
              stroke="#3b82f6"
              fill="#3b82f6"
              fillOpacity={0.5}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1f2937',
                border: 'none',
                borderRadius: '8px',
                color: '#f9fafb'
              }}
            />
          </RadarChart>
        </ResponsiveContainer>
      )}

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-4 mt-6 pt-4 border-t border-gray-200 dark:border-gray-700">
        {metrics.map((m) => {
          const currentRaw = latestData?.[m.key as keyof typeof latestData];
          const previousRaw = chartData[chartData.length - 2]?.[m.key as keyof typeof latestData];
          const currentValue = typeof currentRaw === 'number' ? currentRaw : 0;
          const previousValue = typeof previousRaw === 'number' ? previousRaw : 0;
          const change = previousValue > 0 ? ((currentValue - previousValue) / previousValue * 100) : 0;
          
          return (
            <div key={m.key} className="text-center">
              <p className="text-xs text-gray-500 dark:text-gray-400">{m.label}</p>
              <p className="text-lg font-semibold" style={{ color: m.color }}>
                {currentValue.toLocaleString(undefined, { maximumFractionDigits: 1 })}
              </p>
              <p className={`text-xs ${change >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                {change >= 0 ? '↑' : '↓'} {Math.abs(change).toFixed(1)}%
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
