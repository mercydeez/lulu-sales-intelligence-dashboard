'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  Users, Search, Filter, Download, RefreshCw, ChevronDown,
  TrendingUp, TrendingDown, Star, Clock, Award, Building,
  UserPlus, BarChart3, PieChart, Activity
} from 'lucide-react';
import EmployeePerformanceChart from '@/components/EmployeePerformanceChart';
import EmployeeBioCard from '@/components/EmployeeBioCard';
import NewEmployeeModal from '@/components/NewEmployeeModal';

interface Employee {
  id: number;
  employee_code: string;
  full_name: string;
  first_name: string;
  last_name: string;
  email: string;
  phone?: string;
  role: string;
  department: string;
  designation?: string;
  store_id?: number;
  store_name?: string;
  status: string;
  date_of_joining: string;
  date_of_resignation?: string;
  tenure_days: number;
  photo_url?: string;
  latest_performance_score?: number;
  latest_performance_grade?: string;
}

interface Summary {
  total_employees: number;
  by_status: Record<string, number>;
  by_role: Record<string, number>;
  avg_performance_score: number;
  avg_attendance: number;
  avg_customer_rating: number;
  new_hires_this_month: number;
  resignations_this_month: number;
}

interface RoleAnalytics {
  role: string;
  employee_count: number;
  avg_performance_score: number;
  avg_sales: number;
  avg_customer_rating: number;
  avg_attendance: number;
  total_transactions: number;
}

const ROLE_LABELS: Record<string, string> = {
  super_admin: 'Super Admin',
  regional_manager: 'Regional Manager',
  store_manager: 'Store Manager',
  inventory_manager: 'Inventory Manager',
  sales_executive: 'Sales Executive',
  customer_service: 'Customer Service',
  cashier: 'Senior Cashier',
  analyst: 'Analyst',
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function EmployeesPage() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [roleAnalytics, setRoleAnalytics] = useState<RoleAnalytics[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedRole, setSelectedRole] = useState<string>('');
  const [selectedStore, setSelectedStore] = useState<string>('');
  const [selectedStatus, setSelectedStatus] = useState<string>('active');
  
  // View
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [selectedEmployee, setSelectedEmployee] = useState<Employee | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'employees' | 'analytics'>('overview');
  const [showAddModal, setShowAddModal] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      
      // Fetch employees
      const params = new URLSearchParams();
      if (selectedRole) params.append('role', selectedRole);
      if (selectedStore) params.append('store_id', selectedStore);
      if (selectedStatus) params.append('status', selectedStatus);
      if (searchTerm) params.append('search', searchTerm);
      
      const [empRes, summaryRes, roleRes] = await Promise.all([
        fetch(`${API_URL}/api/employees/employees?${params}`),
        fetch(`${API_URL}/api/employees/employees/analytics/summary`),
        fetch(`${API_URL}/api/employees/employees/analytics/by-role`)
      ]);
      
      if (empRes.ok) {
        const empData = await empRes.json();
        setEmployees(empData.employees || []);
      }
      
      if (summaryRes.ok) {
        const summaryData = await summaryRes.json();
        setSummary(summaryData);
      }
      
      if (roleRes.ok) {
        const roleData = await roleRes.json();
        setRoleAnalytics(roleData.by_role || []);
      }
      
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  }, [selectedRole, selectedStore, selectedStatus, searchTerm]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Summary Cards Component
  const SummaryCards = () => (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Total Employees</p>
            <p className="text-3xl font-bold text-gray-800 dark:text-white">
              {summary?.total_employees || 0}
            </p>
            <p className="text-xs text-green-500 mt-1">
              +{summary?.new_hires_this_month || 0} this month
            </p>
          </div>
          <div className="p-3 bg-blue-100 dark:bg-blue-900 rounded-full">
            <Users className="w-6 h-6 text-blue-600 dark:text-blue-400" />
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Avg Performance</p>
            <p className="text-3xl font-bold text-gray-800 dark:text-white">
              {summary?.avg_performance_score?.toFixed(1) || 0}%
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Across all employees
            </p>
          </div>
          <div className="p-3 bg-green-100 dark:bg-green-900 rounded-full">
            <TrendingUp className="w-6 h-6 text-green-600 dark:text-green-400" />
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Customer Rating</p>
            <p className="text-3xl font-bold text-gray-800 dark:text-white">
              {summary?.avg_customer_rating?.toFixed(2) || 0}
            </p>
            <p className="text-xs text-yellow-500 mt-1">
              ★★★★★
            </p>
          </div>
          <div className="p-3 bg-yellow-100 dark:bg-yellow-900 rounded-full">
            <Star className="w-6 h-6 text-yellow-600 dark:text-yellow-400" />
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">Avg Attendance</p>
            <p className="text-3xl font-bold text-gray-800 dark:text-white">
              {summary?.avg_attendance?.toFixed(1) || 0}%
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Monthly average
            </p>
          </div>
          <div className="p-3 bg-purple-100 dark:bg-purple-900 rounded-full">
            <Clock className="w-6 h-6 text-purple-600 dark:text-purple-400" />
          </div>
        </div>
      </div>
    </div>
  );

  // Role Distribution Component
  const RoleDistribution = () => (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6 mb-6">
      <h3 className="text-lg font-semibold text-gray-800 dark:text-white mb-4">
        Performance by Role
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="text-left text-sm text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
              <th className="pb-3">Role</th>
              <th className="pb-3 text-center">Employees</th>
              <th className="pb-3 text-center">Avg Score</th>
              <th className="pb-3 text-center">Avg Sales</th>
              <th className="pb-3 text-center">Rating</th>
              <th className="pb-3 text-center">Attendance</th>
            </tr>
          </thead>
          <tbody>
            {roleAnalytics.map((role) => (
              <tr 
                key={role.role} 
                className="border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer"
                onClick={() => setSelectedRole(role.role)}
              >
                <td className="py-3">
                  <span className="font-medium text-gray-800 dark:text-white">
                    {ROLE_LABELS[role.role] || role.role}
                  </span>
                </td>
                <td className="py-3 text-center">
                  <span className="px-2 py-1 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded-full text-sm">
                    {role.employee_count}
                  </span>
                </td>
                <td className="py-3 text-center">
                  <span className={`font-semibold ${role.avg_performance_score >= 80 ? 'text-green-500' : role.avg_performance_score >= 60 ? 'text-yellow-500' : 'text-red-500'}`}>
                    {role.avg_performance_score.toFixed(1)}%
                  </span>
                </td>
                <td className="py-3 text-center text-gray-600 dark:text-gray-400">
                  {role.avg_sales.toLocaleString('en-AE', { style: 'currency', currency: 'AED', maximumFractionDigits: 0 })}
                </td>
                <td className="py-3 text-center">
                  <div className="flex items-center justify-center gap-1">
                    <Star className="w-4 h-4 text-yellow-500 fill-yellow-500" />
                    <span className="text-gray-600 dark:text-gray-400">{role.avg_customer_rating.toFixed(1)}</span>
                  </div>
                </td>
                <td className="py-3 text-center text-gray-600 dark:text-gray-400">
                  {role.avg_attendance.toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );

  // Employee Grid Component
  const EmployeeGrid = () => (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {employees.map((employee) => (
        <EmployeeBioCard
          key={employee.id}
          employee={employee}
          compact={true}
          onClick={() => setSelectedEmployee(employee)}
        />
      ))}
    </div>
  );

  // Employee List Component
  const EmployeeList = () => (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg overflow-hidden">
      <table className="w-full">
        <thead className="bg-gray-50 dark:bg-gray-700">
          <tr className="text-left text-sm text-gray-500 dark:text-gray-400">
            <th className="px-6 py-3">Employee</th>
            <th className="px-6 py-3">Role</th>
            <th className="px-6 py-3">Store</th>
            <th className="px-6 py-3">Joined</th>
            <th className="px-6 py-3 text-center">Performance</th>
            <th className="px-6 py-3 text-center">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
          {employees.map((employee) => (
            <tr 
              key={employee.id}
              className="hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer"
              onClick={() => setSelectedEmployee(employee)}
            >
              <td className="px-6 py-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-semibold text-sm">
                    {employee.first_name.charAt(0)}{employee.last_name.charAt(0)}
                  </div>
                  <div>
                    <p className="font-medium text-gray-800 dark:text-white">{employee.full_name}</p>
                    <p className="text-xs text-gray-500">{employee.employee_code}</p>
                  </div>
                </div>
              </td>
              <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-400">
                {ROLE_LABELS[employee.role] || employee.role}
              </td>
              <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-400">
                {employee.store_name || 'HQ'}
              </td>
              <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-400">
                {new Date(employee.date_of_joining).toLocaleDateString('en-AE', { month: 'short', year: 'numeric' })}
              </td>
              <td className="px-6 py-4 text-center">
                <span className={`px-2 py-1 rounded-full text-xs font-bold ${
                  employee.latest_performance_grade === 'A+' || employee.latest_performance_grade === 'A' 
                    ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                    : employee.latest_performance_grade === 'B+' || employee.latest_performance_grade === 'B'
                    ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
                    : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
                }`}>
                  {employee.latest_performance_grade || 'N/A'}
                </span>
              </td>
              <td className="px-6 py-4 text-center">
                <span className={`px-2 py-1 rounded-full text-xs ${
                  employee.status === 'active' 
                    ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                    : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                }`}>
                  {employee.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  if (loading && !employees.length) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-6">
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded w-1/4"></div>
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-32 bg-gray-200 dark:bg-gray-700 rounded-xl"></div>
            ))}
          </div>
          <div className="h-96 bg-gray-200 dark:bg-gray-700 rounded-xl"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-6">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800 dark:text-white">
            Employee Performance Dashboard
          </h1>
          <p className="text-gray-500 dark:text-gray-400">
            Monitor and analyze employee performance metrics
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={fetchData}
            className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <UserPlus className="w-4 h-4" />
            Add Employee
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        {[
          { id: 'overview', label: 'Overview', icon: BarChart3 },
          { id: 'employees', label: 'Employees', icon: Users },
          { id: 'analytics', label: 'Analytics', icon: PieChart },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as typeof activeTab)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
              activeTab === tab.id
                ? 'bg-blue-600 text-white'
                : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <>
          <SummaryCards />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <EmployeePerformanceChart chartType="line" title="Performance Trend" />
            <EmployeePerformanceChart chartType="bar" title="Monthly Comparison" />
          </div>
          <RoleDistribution />
        </>
      )}

      {/* Employees Tab */}
      {activeTab === 'employees' && (
        <>
          {/* Filters */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-4 mb-6">
            <div className="flex flex-wrap gap-4">
              <div className="flex-1 min-w-[200px]">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search employees..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-full pl-10 pr-4 py-2 border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-800 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
              <select
                value={selectedRole}
                onChange={(e) => setSelectedRole(e.target.value)}
                className="px-4 py-2 border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-800 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">All Roles</option>
                {Object.entries(ROLE_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
              <select
                value={selectedStatus}
                onChange={(e) => setSelectedStatus(e.target.value)}
                className="px-4 py-2 border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-800 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">All Status</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
                <option value="terminated">Terminated</option>
              </select>
              <div className="flex gap-2">
                <button
                  onClick={() => setViewMode('grid')}
                  className={`p-2 rounded-lg ${viewMode === 'grid' ? 'bg-blue-100 dark:bg-blue-900 text-blue-600' : 'bg-gray-100 dark:bg-gray-700 text-gray-600'}`}
                >
                  <BarChart3 className="w-5 h-5" />
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  className={`p-2 rounded-lg ${viewMode === 'list' ? 'bg-blue-100 dark:bg-blue-900 text-blue-600' : 'bg-gray-100 dark:bg-gray-700 text-gray-600'}`}
                >
                  <Activity className="w-5 h-5" />
                </button>
              </div>
            </div>
          </div>

          {/* Employee Display */}
          {employees.length === 0 ? (
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-12 text-center">
              <Users className="w-16 h-16 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
              <p className="text-gray-500 dark:text-gray-400">No employees found</p>
            </div>
          ) : viewMode === 'grid' ? (
            <EmployeeGrid />
          ) : (
            <EmployeeList />
          )}
        </>
      )}

      {/* Analytics Tab */}
      {activeTab === 'analytics' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <EmployeePerformanceChart chartType="radar" title="Performance Radar" />
          <EmployeePerformanceChart role="sales_executive" chartType="line" title="Sales Executive Trend" />
          <EmployeePerformanceChart role="store_manager" chartType="bar" title="Store Manager Performance" />
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
            <h3 className="text-lg font-semibold text-gray-800 dark:text-white mb-4">
              Role Distribution
            </h3>
            <div className="space-y-4">
              {summary?.by_role && Object.entries(summary.by_role).map(([role, count]) => {
                const total = summary.total_employees || 1;
                const percentage = (count / total) * 100;
                return (
                  <div key={role}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-gray-600 dark:text-gray-400">{ROLE_LABELS[role] || role}</span>
                      <span className="text-gray-800 dark:text-white font-medium">{count}</span>
                    </div>
                    <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-blue-500 to-purple-600 rounded-full"
                        style={{ width: `${percentage}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Employee Detail Modal */}
      {selectedEmployee && (
        <div 
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setSelectedEmployee(null)}
        >
          <div 
            className="max-w-2xl w-full max-h-[90vh] overflow-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <EmployeeBioCard employee={selectedEmployee} />
            <div className="mt-4">
              <EmployeePerformanceChart 
                employeeId={selectedEmployee.id} 
                chartType="line" 
                title={`${selectedEmployee.full_name}'s Performance`} 
              />
            </div>
          </div>
        </div>
      )}

      {/* Add Employee Modal */}
      <NewEmployeeModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        onSuccess={() => {
          setShowAddModal(false);
          fetchData();
        }}
      />
    </div>
  );
}
