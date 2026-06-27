'use client';

import { useState, useEffect, useCallback } from 'react';
import { Users, UserPlus, RefreshCw, BarChart3, PieChart } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Button, Tabs, Reveal } from '@/components/ui';
import {
  EmployeeSummaryCards,
  RolePerformanceTable,
  RoleDistribution,
  EmployeeFilters,
  EmployeeListView,
  EmployeePerformanceChart,
  EmployeeFormModal,
  EmployeeDetailModal,
  Employee,
  EmployeeSummary,
  RoleAnalytics,
  EmployeeTab,
  EmployeeViewMode,
} from '@/components/employees';

export default function EmployeesPage() {
  const { authFetch, hasPermission } = useAuth();
  const canManage = hasPermission('can_manage_employees') || hasPermission('can_manage_users');

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [summary, setSummary] = useState<EmployeeSummary | null>(null);
  const [roleAnalytics, setRoleAnalytics] = useState<RoleAnalytics[]>([]);
  const [loading, setLoading] = useState(true);

  const [activeTab, setActiveTab] = useState<EmployeeTab>('overview');
  const [search, setSearch] = useState('');
  const [role, setRole] = useState('');
  const [status, setStatus] = useState('active');
  const [viewMode, setViewMode] = useState<EmployeeViewMode>('grid');
  const [selected, setSelected] = useState<Employee | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (role) params.append('role', role);
      if (status) params.append('status', status);
      if (search) params.append('search', search);

      const [empRes, summaryRes, roleRes] = await Promise.all([
        authFetch(`/api/employees/employees?${params}`),
        authFetch('/api/employees/employees/analytics/summary'),
        authFetch('/api/employees/employees/analytics/by-role'),
      ]);
      if (empRes.ok) setEmployees((await empRes.json()).employees ?? []);
      if (summaryRes.ok) setSummary(await summaryRes.json());
      if (roleRes.ok) setRoleAnalytics((await roleRes.json()).by_role ?? []);
    } catch (err) {
      console.error('Failed to fetch employee data:', err);
    } finally {
      setLoading(false);
    }
  }, [authFetch, role, status, search]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title="Employee Performance"
          description="Monitor and analyze workforce performance across stores and roles"
          icon={<Users className="w-5 h-5" />}
          actions={
            <>
              <Button variant="secondary" size="md" onClick={fetchData} aria-label="Refresh">
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </Button>
              {canManage && (
                <Button variant="primary" size="md" onClick={() => setShowAdd(true)}>
                  <UserPlus className="w-4 h-4" />
                  Add Employee
                </Button>
              )}
            </>
          }
        />

        <Tabs
          className="mb-6"
          value={activeTab}
          onChange={(id) => setActiveTab(id as EmployeeTab)}
          items={[
            { id: 'overview', label: 'Overview', icon: <BarChart3 className="w-4 h-4" /> },
            { id: 'employees', label: 'Employees', icon: <Users className="w-4 h-4" /> },
            { id: 'analytics', label: 'Analytics', icon: <PieChart className="w-4 h-4" /> },
          ]}
        />

        {activeTab === 'overview' && (
          <Reveal key="tab-overview">
            <EmployeeSummaryCards summary={summary} loading={loading} />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 my-6">
              <EmployeePerformanceChart chartType="line" title="Performance Trend" />
              <EmployeePerformanceChart chartType="bar" title="Monthly Comparison" />
            </div>
            <RolePerformanceTable
              roles={roleAnalytics}
              loading={loading}
              onSelectRole={(r) => {
                setRole(r);
                setActiveTab('employees');
              }}
            />
          </Reveal>
        )}

        {activeTab === 'employees' && (
          <Reveal key="tab-employees">
            <EmployeeFilters
              search={search}
              onSearchChange={setSearch}
              role={role}
              onRoleChange={setRole}
              status={status}
              onStatusChange={setStatus}
              viewMode={viewMode}
              onViewModeChange={setViewMode}
            />
            <EmployeeListView employees={employees} loading={loading} viewMode={viewMode} onSelect={setSelected} />
          </Reveal>
        )}

        {activeTab === 'analytics' && (
          <Reveal key="tab-analytics" className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <EmployeePerformanceChart chartType="radar" title="Performance Radar" />
            <RoleDistribution summary={summary} loading={loading} />
            <EmployeePerformanceChart role="sales_executive" chartType="line" title="Sales Executive Trend" />
            <EmployeePerformanceChart role="store_manager" chartType="bar" title="Store Manager Performance" />
          </Reveal>
        )}
      </div>

      <EmployeeDetailModal employee={selected} onClose={() => setSelected(null)} />
      {canManage && (
        <EmployeeFormModal open={showAdd} onClose={() => setShowAdd(false)} onSuccess={fetchData} />
      )}
    </main>
  );
}
