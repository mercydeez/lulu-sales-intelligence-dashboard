'use client';

import React, { useState, useEffect } from 'react';
import { 
  Shield, Users, Store, Settings, Key, Activity,
  Plus, Edit2, Trash2, Check, X, Search, RefreshCw,
  UserPlus, Lock, Unlock, Mail, Calendar, ChevronDown,
  Briefcase, TrendingUp, Award, Zap
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { ROLE_DISPLAY_NAMES, UserRole } from '@/types/auth';

interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login?: string;
}

interface StoreInfo {
  id: number;
  name: string;
  location: string;
  manager?: string;
  status: 'active' | 'inactive';
}

export default function AdminPage() {
  const { user, authFetch, hasRole } = useAuth();
  const [activeTab, setActiveTab] = useState<'users' | 'stores' | 'employees' | 'settings'>('users');
  const [loading, setLoading] = useState(true);
  const [users, setUsers] = useState<User[]>([]);
  const [stores, setStores] = useState<StoreInfo[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [showAddUser, setShowAddUser] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [dashboardStats, setDashboardStats] = useState<any>(null);
  const [employees, setEmployees] = useState<any[]>([]);
  const [employeeSearch, setEmployeeSearch] = useState('');
  const [employeeStats, setEmployeeStats] = useState<any>(null);
  const [livePerformance, setLivePerformance] = useState<any[]>([]);

  // Check if user has admin access
  const isAdmin = hasRole(['super_admin']);

  useEffect(() => {
    if (isAdmin) {
      fetchData();
    }
  }, [isAdmin]);

  const fetchData = async () => {
    setLoading(true);
    try {
      // Fetch users from admin API
      const usersRes = await authFetch('/api/admin/users');
      if (usersRes.ok) {
        const data = await usersRes.json();
        setUsers(data.users || []);
      } else {
        // Try auth endpoint as fallback
        const authUsersRes = await authFetch('/api/auth/users');
        if (authUsersRes.ok) {
          const data = await authUsersRes.json();
          setUsers(data.users || []);
        } else {
          setUsers(generateMockUsers());
        }
      }

      // Fetch stores from admin API
      const storesRes = await authFetch('/api/admin/stores');
      if (storesRes.ok) {
        const data = await storesRes.json();
        const storeData = data.stores?.map((s: any) => ({
          id: s.id,
          name: s.name,
          location: s.location,
          manager: s.manager || 'Not Assigned',
          status: s.status || 'active',
          total_sales_30d: s.total_sales_30d || 0
        })) || [];
        setStores(storeData);
      } else {
        setStores(generateMockStores());
      }

      // Fetch admin dashboard stats
      const dashRes = await authFetch('/api/admin/dashboard');
      if (dashRes.ok) {
        const data = await dashRes.json();
        setDashboardStats(data);
      }

      // Fetch employees
      try {
        const empRes = await authFetch('/api/employees/employees');
        if (empRes.ok) {
          const empData = await empRes.json();
          setEmployees(empData.employees || []);
        }
      } catch (e) {
        console.error('Failed to fetch employees:', e);
      }

      // Fetch employee stats
      try {
        const statsRes = await authFetch('/api/employees/stats/overview');
        if (statsRes.ok) {
          const statsData = await statsRes.json();
          setEmployeeStats(statsData);
        }
      } catch (e) {
        console.error('Failed to fetch employee stats:', e);
      }
    } catch (error) {
      console.error('Failed to fetch admin data:', error);
      setUsers(generateMockUsers());
      setStores(generateMockStores());
    } finally {
      setLoading(false);
    }
  };

  const generateMockUsers = (): User[] => [
    {
      id: 1,
      email: 'yash@lulu.ae',
      first_name: 'Yash',
      last_name: 'Patel',
      role: 'super_admin',
      is_active: true,
      created_at: '2025-01-01T00:00:00Z',
      last_login: '2026-01-31T10:30:00Z'
    },
    {
      id: 2,
      email: 'krishna@lulu.ae',
      first_name: 'Krishna',
      last_name: 'Kumar',
      role: 'regional_manager',
      is_active: true,
      created_at: '2025-01-15T00:00:00Z',
      last_login: '2026-01-30T14:20:00Z'
    },
    {
      id: 3,
      email: 'atharva@lulu.ae',
      first_name: 'Atharva',
      last_name: 'Sharma',
      role: 'store_manager',
      is_active: true,
      created_at: '2025-02-01T00:00:00Z',
      last_login: '2026-01-29T09:15:00Z'
    },
    {
      id: 4,
      email: 'rahul.inv@lulu.ae',
      first_name: 'Rahul',
      last_name: 'Verma',
      role: 'inventory_manager',
      is_active: true,
      created_at: '2025-03-01T00:00:00Z',
      last_login: '2026-01-31T08:45:00Z'
    },
    {
      id: 5,
      email: 'priya.sales@lulu.ae',
      first_name: 'Priya',
      last_name: 'Sharma',
      role: 'sales_executive',
      is_active: true,
      created_at: '2025-03-15T00:00:00Z',
      last_login: '2026-01-31T09:00:00Z'
    },
    {
      id: 6,
      email: 'ahmed.cashier@lulu.ae',
      first_name: 'Ahmed',
      last_name: 'Hassan',
      role: 'cashier',
      is_active: true,
      created_at: '2025-04-01T00:00:00Z',
      last_login: '2026-01-31T07:30:00Z'
    },
    {
      id: 7,
      email: 'security@lulu.ae',
      first_name: 'Mohammed',
      last_name: 'Ali',
      role: 'security',
      is_active: true,
      created_at: '2025-04-15T00:00:00Z',
      last_login: '2026-01-31T06:00:00Z'
    },
    {
      id: 8,
      email: 'sara.support@lulu.ae',
      first_name: 'Sara',
      last_name: 'Khan',
      role: 'inventory_support',
      is_active: true,
      created_at: '2025-05-01T00:00:00Z',
      last_login: '2026-01-30T16:00:00Z'
    },
    {
      id: 9,
      email: 'intern.sales@lulu.ae',
      first_name: 'Ali',
      last_name: 'Raza',
      role: 'sales_intern',
      is_active: true,
      created_at: '2025-06-01T00:00:00Z',
      last_login: '2026-01-31T10:00:00Z'
    },
    {
      id: 10,
      email: 'procurement@lulu.ae',
      first_name: 'Fatima',
      last_name: 'Noor',
      role: 'procurement_officer',
      is_active: true,
      created_at: '2025-02-15T00:00:00Z',
      last_login: '2026-01-31T11:00:00Z'
    },
    {
      id: 11,
      email: 'warehouse@lulu.ae',
      first_name: 'Ravi',
      last_name: 'Singh',
      role: 'warehouse_supervisor',
      is_active: true,
      created_at: '2025-03-10T00:00:00Z',
      last_login: '2026-01-31T05:30:00Z'
    },
    {
      id: 12,
      email: 'customer.service@lulu.ae',
      first_name: 'Aisha',
      last_name: 'Malik',
      role: 'customer_service',
      is_active: true,
      created_at: '2025-04-20T00:00:00Z',
      last_login: '2026-01-31T09:30:00Z'
    },
  ];

  const generateMockStores = (): StoreInfo[] => [
    { id: 1, name: 'Al Barsha', location: 'Dubai', manager: 'Atharva Sharma', status: 'active' },
    { id: 2, name: 'Deira City Centre', location: 'Dubai', manager: 'Ahmed Hassan', status: 'active' },
    { id: 3, name: 'Karama', location: 'Dubai', manager: 'Sara Ali', status: 'active' },
    { id: 4, name: 'Mushrif Mall', location: 'Abu Dhabi', manager: 'Mohammed Khan', status: 'active' },
    { id: 5, name: 'Al Wahda', location: 'Abu Dhabi', manager: 'Fatima Noor', status: 'active' },
  ];

  const filteredUsers = users.filter(u => 
    u.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
    u.first_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    u.last_name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const filteredEmployees = employees.filter((emp: any) =>
    emp.full_name?.toLowerCase().includes(employeeSearch.toLowerCase()) ||
    emp.employee_code?.toLowerCase().includes(employeeSearch.toLowerCase()) ||
    emp.department?.toLowerCase().includes(employeeSearch.toLowerCase()) ||
    emp.store_name?.toLowerCase().includes(employeeSearch.toLowerCase())
  );

  // SSE for real-time performance updates
  useEffect(() => {
    if (activeTab !== 'employees') return;
    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    let eventSource: EventSource | null = null;
    try {
      eventSource = new EventSource(`${API_URL}/api/employees/employees/performance/live`);
      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.updates) {
            setLivePerformance(data.updates);
          }
        } catch (e) { /* ignore parse errors */ }
      };
      eventSource.onerror = () => {
        eventSource?.close();
      };
    } catch (e) { /* SSE not supported */ }
    return () => { eventSource?.close(); };
  }, [activeTab]);

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-AE', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getRoleBadgeClass = (role: UserRole) => {
    switch (role) {
      case 'super_admin':
        return 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400';
      case 'regional_manager':
        return 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400';
      case 'store_manager':
        return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400';
      case 'inventory_manager':
        return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
      case 'procurement_officer':
        return 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400';
      case 'warehouse_supervisor':
        return 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400';
      case 'sales_executive':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400';
      case 'cashier':
        return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'security':
        return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
      case 'inventory_support':
        return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400';
      case 'sales_intern':
        return 'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400';
      case 'customer_service':
        return 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400';
      default:
        return 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-400';
    }
  };

  if (!isAdmin) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col items-center justify-center h-[60vh]">
            <Shield className="w-16 h-16 text-red-500 mb-4" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Access Denied</h1>
            <p className="text-gray-600 dark:text-gray-400">You don't have permission to access the Admin panel.</p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        {/* Page Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
              <Shield className="w-8 h-8 text-purple-600" />
              Admin Panel
            </h1>
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              Manage users, stores, and system settings
            </p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-6 border-b border-gray-200 dark:border-gray-700">
          <button
            onClick={() => setActiveTab('users')}
            className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors border-b-2 -mb-px ${
              activeTab === 'users'
                ? 'text-purple-600 border-purple-600'
                : 'text-gray-500 border-transparent hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <Users className="w-5 h-5" />
            Users
          </button>
          <button
            onClick={() => setActiveTab('stores')}
            className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors border-b-2 -mb-px ${
              activeTab === 'stores'
                ? 'text-purple-600 border-purple-600'
                : 'text-gray-500 border-transparent hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <Store className="w-5 h-5" />
            Stores
          </button>
          <button
            onClick={() => setActiveTab('employees')}
            className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors border-b-2 -mb-px ${
              activeTab === 'employees'
                ? 'text-purple-600 border-purple-600'
                : 'text-gray-500 border-transparent hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <Briefcase className="w-5 h-5" />
            Employees
          </button>
          <button
            onClick={() => setActiveTab('settings')}
            className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors border-b-2 -mb-px ${
              activeTab === 'settings'
                ? 'text-purple-600 border-purple-600'
                : 'text-gray-500 border-transparent hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <Settings className="w-5 h-5" />
            Settings
          </button>
        </div>

        {/* Users Tab */}
        {activeTab === 'users' && (
          <div className="space-y-6">
            {/* Actions Bar */}
            <div className="flex items-center justify-between">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search users..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                />
              </div>
              <button
                onClick={() => setShowAddUser(true)}
                className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
              >
                <UserPlus className="w-5 h-5" />
                Add User
              </button>
            </div>

            {/* Users Table */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
              <table className="w-full">
                <thead className="bg-gray-50 dark:bg-gray-700/50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">User</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Role</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Status</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Last Login</th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                  {filteredUsers.map((u) => (
                    <tr key={u.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-purple-500 to-pink-600 flex items-center justify-center text-white font-semibold">
                            {u.first_name[0]}{u.last_name[0]}
                          </div>
                          <div>
                            <p className="font-medium text-gray-900 dark:text-white">
                              {u.first_name} {u.last_name}
                            </p>
                            <p className="text-sm text-gray-500 dark:text-gray-400">{u.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${getRoleBadgeClass(u.role)}`}>
                          {ROLE_DISPLAY_NAMES[u.role]}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                          u.is_active
                            ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                            : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                        }`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? 'bg-green-500' : 'bg-red-500'}`} />
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400">
                        {u.last_login ? formatDate(u.last_login) : 'Never'}
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => setEditingUser(u)}
                            className="p-2 text-gray-400 hover:text-purple-600 hover:bg-purple-50 dark:hover:bg-purple-900/20 rounded-lg transition-colors"
                            title="Edit User"
                          >
                            <Edit2 className="w-4 h-4" />
                          </button>
                          <button
                            className="p-2 text-gray-400 hover:text-yellow-600 hover:bg-yellow-50 dark:hover:bg-yellow-900/20 rounded-lg transition-colors"
                            title={u.is_active ? 'Deactivate' : 'Activate'}
                          >
                            {u.is_active ? <Lock className="w-4 h-4" /> : <Unlock className="w-4 h-4" />}
                          </button>
                          <button
                            className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                            title="Delete User"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Stores Tab */}
        {activeTab === 'stores' && (
          <div className="space-y-6">
            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
                    <Store className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                  </div>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Total Stores</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">{stores.length}</p>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
                    <Activity className="w-5 h-5 text-green-600 dark:text-green-400" />
                  </div>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Active</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {stores.filter(s => s.status === 'active').length}
                </p>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
                    <Users className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                  </div>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Total Users</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">{users.length}</p>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 bg-orange-100 dark:bg-orange-900/30 rounded-lg">
                    <Key className="w-5 h-5 text-orange-600 dark:text-orange-400" />
                  </div>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Admins</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {users.filter(u => u.role === 'super_admin').length}
                </p>
              </div>
            </div>

            {/* Stores Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {stores.map((store) => (
                <div key={store.id} className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-100 dark:border-gray-700">
                  <div className="flex items-start justify-between mb-4">
                    <div className="p-3 bg-purple-100 dark:bg-purple-900/30 rounded-xl">
                      <Store className="w-6 h-6 text-purple-600 dark:text-purple-400" />
                    </div>
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${
                      store.status === 'active'
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                    }`}>
                      {store.status}
                    </span>
                  </div>
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">{store.name}</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">{store.location}</p>
                  <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
                    <p className="text-xs text-gray-500 dark:text-gray-400">Manager</p>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">{store.manager || 'Not Assigned'}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Employees Tab */}
        {activeTab === 'employees' && (
          <div className="space-y-6">
            {/* Employee Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
                    <Briefcase className="w-5 h-5 text-blue-600 dark:text-blue-400" />
                  </div>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Total Employees</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {employeeStats?.total_employees || employees.length}
                </p>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
                    <TrendingUp className="w-5 h-5 text-green-600 dark:text-green-400" />
                  </div>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Avg Performance</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {employeeStats?.avg_performance_score?.toFixed(1) || '—'}
                </p>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
                    <Award className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                  </div>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Top Performers</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {employeeStats?.top_performers || employees.filter((e: any) => (e.performance_score || 0) >= 85).length}
                </p>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-xl p-6 border border-gray-100 dark:border-gray-700">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
                    <Zap className="w-5 h-5 text-purple-600 dark:text-purple-400" />
                  </div>
                  <span className="text-sm text-gray-500 dark:text-gray-400">Departments</span>
                </div>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">
                  {employeeStats?.departments || new Set(employees.map((e: any) => e.department)).size}
                </p>
              </div>
            </div>

            {/* Real-time Performance Pulse */}
            {livePerformance.length > 0 && (
              <div className="bg-gradient-to-r from-purple-600 to-pink-600 rounded-xl p-4 text-white">
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                  <span className="text-sm font-medium">Live Performance Updates</span>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {livePerformance.slice(0, 4).map((perf: any, idx: number) => (
                    <div key={idx} className="bg-white/10 rounded-lg p-3 backdrop-blur-sm">
                      <p className="text-xs text-white/70">{perf.employee_name || `Employee #${perf.employee_id}`}</p>
                      <p className="text-lg font-bold">{perf.score?.toFixed(1) || '—'}</p>
                      <p className="text-xs text-white/60">{perf.metric || 'Performance'}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Search & Actions */}
            <div className="flex items-center justify-between">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search employees by name, code, department..."
                  value={employeeSearch}
                  onChange={(e) => setEmployeeSearch(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => fetchData()}
                  className="p-2 text-gray-400 hover:text-purple-600 hover:bg-purple-50 dark:hover:bg-purple-900/20 rounded-lg transition-colors"
                  title="Refresh"
                >
                  <RefreshCw className="w-5 h-5" />
                </button>
                <a
                  href="/employees"
                  className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
                >
                  <Briefcase className="w-5 h-5" />
                  Full Employee Page
                </a>
              </div>
            </div>

            {/* Employees Table */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
              <table className="w-full">
                <thead className="bg-gray-50 dark:bg-gray-700/50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Employee</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Department</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Store</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Role</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Performance</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                  {filteredEmployees.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">
                        {employeeSearch ? 'No employees match your search' : 'No employees found'}
                      </td>
                    </tr>
                  ) : (
                    filteredEmployees.slice(0, 20).map((emp: any) => {
                      const score = emp.performance_score || 0;
                      const grade = score >= 90 ? 'A+' : score >= 80 ? 'A' : score >= 70 ? 'B' : score >= 60 ? 'C' : 'D';
                      const gradeColor = score >= 80 ? 'text-green-600 bg-green-100 dark:bg-green-900/30 dark:text-green-400'
                        : score >= 60 ? 'text-amber-600 bg-amber-100 dark:bg-amber-900/30 dark:text-amber-400'
                        : 'text-red-600 bg-red-100 dark:bg-red-900/30 dark:text-red-400';
                      return (
                        <tr key={emp.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-600 flex items-center justify-center text-white font-semibold text-sm">
                                {emp.full_name?.split(' ').map((n: string) => n[0]).join('').slice(0, 2) || '??'}
                              </div>
                              <div>
                                <p className="font-medium text-gray-900 dark:text-white">{emp.full_name || 'Unknown'}</p>
                                <p className="text-xs text-gray-500 dark:text-gray-400">{emp.employee_code || ''}</p>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 text-sm text-gray-700 dark:text-gray-300">{emp.department || '—'}</td>
                          <td className="px-6 py-4 text-sm text-gray-700 dark:text-gray-300">{emp.store_name || '—'}</td>
                          <td className="px-6 py-4">
                            <span className="px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300">
                              {emp.role?.replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase()) || '—'}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-2">
                              <div className="w-16 bg-gray-200 dark:bg-gray-600 rounded-full h-2">
                                <div
                                  className={`h-2 rounded-full ${score >= 80 ? 'bg-green-500' : score >= 60 ? 'bg-amber-500' : 'bg-red-500'}`}
                                  style={{ width: `${Math.min(score, 100)}%` }}
                                />
                              </div>
                              <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${gradeColor}`}>{grade}</span>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium ${
                              emp.status === 'active'
                                ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                                : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                            }`}>
                              <span className={`w-1.5 h-1.5 rounded-full ${emp.status === 'active' ? 'bg-green-500' : 'bg-red-500'}`} />
                              {emp.status || 'active'}
                            </span>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
              {filteredEmployees.length > 20 && (
                <div className="px-6 py-3 border-t border-gray-100 dark:border-gray-700 text-center">
                  <a href="/employees" className="text-sm text-purple-600 hover:text-purple-700 font-medium">
                    View all {filteredEmployees.length} employees →
                  </a>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Settings Tab */}
        {activeTab === 'settings' && (
          <div className="space-y-6">
            {/* System Settings */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700">
              <div className="p-6 border-b border-gray-100 dark:border-gray-700">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">System Settings</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Configure global system settings</p>
              </div>
              <div className="p-6 space-y-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-gray-900 dark:text-white">Enable Real-time Updates</p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Stream live sales data to dashboards</p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" defaultChecked className="sr-only peer" />
                    <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-purple-300 dark:peer-focus:ring-purple-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-purple-600"></div>
                  </label>
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-gray-900 dark:text-white">AI Predictions</p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Enable AI-powered sales forecasting</p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" defaultChecked className="sr-only peer" />
                    <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-purple-300 dark:peer-focus:ring-purple-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-purple-600"></div>
                  </label>
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-gray-900 dark:text-white">Email Notifications</p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Send email alerts for critical events</p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" className="sr-only peer" />
                    <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-purple-300 dark:peer-focus:ring-purple-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-purple-600"></div>
                  </label>
                </div>
              </div>
            </div>

            {/* Data Retention */}
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700">
              <div className="p-6 border-b border-gray-100 dark:border-gray-700">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Data Retention</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Configure how long data is stored</p>
              </div>
              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Sales Data Retention
                  </label>
                  <select className="w-full px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                    <option>90 Days</option>
                    <option>180 Days</option>
                    <option>1 Year</option>
                    <option>2 Years</option>
                    <option>Forever</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Log Retention
                  </label>
                  <select className="w-full px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                    <option>30 Days</option>
                    <option>60 Days</option>
                    <option>90 Days</option>
                    <option>180 Days</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Save Button */}
            <div className="flex justify-end">
              <button className="px-6 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors">
                Save Settings
              </button>
            </div>
          </div>
        )}

      {/* Add User Modal */}
      {showAddUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-xl w-full max-w-md p-6 m-4">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Add New User</h2>
              <button
                onClick={() => setShowAddUser(false)}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">First Name</label>
                  <input
                    type="text"
                    className="w-full px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                    placeholder="John"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Last Name</label>
                  <input
                    type="text"
                    className="w-full px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                    placeholder="Doe"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Email</label>
                <input
                  type="email"
                  className="w-full px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                  placeholder="john.doe@lulu.ae"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Role</label>
                <select className="w-full px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                  <option value="store_manager">Store Manager</option>
                  <option value="regional_manager">Regional Manager</option>
                  <option value="super_admin">Super Admin</option>
                  <option value="inventory_manager">Inventory Manager</option>
                  <option value="procurement_officer">Procurement Officer</option>
                  <option value="warehouse_supervisor">Warehouse Supervisor</option>
                  <option value="sales_executive">Sales Executive</option>
                  <option value="analyst">Business Analyst</option>
                  <option value="customer_service">Customer Service</option>
                  <option value="inventory_support">Inventory Support</option>
                  <option value="cashier">Cashier</option>
                  <option value="sales_intern">Sales Intern</option>
                  <option value="security">Security</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Password</label>
                <input
                  type="password"
                  className="w-full px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                  placeholder="••••••••"
                />
              </div>
              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowAddUser(false)}
                  className="flex-1 px-4 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700"
                >
                  Create User
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      </div>
    </main>
  );
}
