'use client';

import { useState, useEffect, useCallback } from 'react';
import { Shield, Users, Store, Activity, LayoutDashboard, RefreshCw, Lock } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Button, Tabs, Card, EmptyState } from '@/components/ui';
import {
  AdminDashboardCards,
  AdminTrendChart,
  UsersTable,
  StoresTable,
  ActivityFeed,
  AdminUser,
  AdminStore,
  ActivityItem,
  AdminDashboard,
  AdminTab,
  NewUserModal,
} from '@/components/admin';

export default function AdminPage() {
  const { hasRole, authFetch } = useAuth();
  const isAdmin = hasRole(['super_admin']);

  const [activeTab, setActiveTab] = useState<AdminTab>('overview');
  const [dashboard, setDashboard] = useState<AdminDashboard | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [stores, setStores] = useState<AdminStore[]>([]);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [userSearch, setUserSearch] = useState('');
  const [showNewUser, setShowNewUser] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [dashRes, usersRes, storesRes, activityRes] = await Promise.all([
        authFetch('/api/admin/dashboard'),
        authFetch('/api/admin/users?limit=100'),
        authFetch('/api/admin/stores'),
        authFetch('/api/admin/activity?limit=20'),
      ]);
      if (dashRes.ok) setDashboard(await dashRes.json());
      if (usersRes.ok) setUsers((await usersRes.json()).users ?? []);
      if (storesRes.ok) setStores((await storesRes.json()).stores ?? []);
      if (activityRes.ok) setActivities((await activityRes.json()).activities ?? []);
    } catch (err) {
      console.error('Failed to fetch admin data:', err);
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    if (isAdmin) fetchData();
    else setLoading(false);
  }, [isAdmin, fetchData]);

  if (!isAdmin) {
    return (
      <main className="min-h-screen p-4 md:p-8">
        <div className="max-w-7xl mx-auto">
          <PageHeader title="Administration" description="System administration console" icon={<Shield className="w-5 h-5" />} />
          <Card variant="glass" padding="lg">
            <EmptyState
              icon={<Lock className="w-6 h-6" />}
              title="Super-admin access required"
              description="This console is restricted to super-admin accounts. Contact your administrator if you believe this is an error."
            />
          </Card>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto">
        <PageHeader
          title="Administration"
          description="Platform overview, accounts, and store directory"
          icon={<Shield className="w-5 h-5" />}
          actions={
            <Button variant="secondary" size="md" onClick={fetchData} aria-label="Refresh">
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          }
        />

        <Tabs
          className="mb-6"
          value={activeTab}
          onChange={(id) => setActiveTab(id as AdminTab)}
          items={[
            { id: 'overview', label: 'Overview', icon: <LayoutDashboard className="w-4 h-4" /> },
            { id: 'users', label: 'Users', icon: <Users className="w-4 h-4" /> },
            { id: 'stores', label: 'Stores', icon: <Store className="w-4 h-4" /> },
            { id: 'activity', label: 'Activity', icon: <Activity className="w-4 h-4" /> },
          ]}
        />

        {activeTab === 'overview' && (
          <>
            <AdminDashboardCards dashboard={dashboard} loading={loading} />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <AdminTrendChart dashboard={dashboard} loading={loading} />
              <ActivityFeed activities={activities} loading={loading} />
            </div>
          </>
        )}

        {activeTab === 'users' && (
          <UsersTable
            users={users}
            loading={loading}
            search={userSearch}
            onSearchChange={setUserSearch}
            onAddUser={() => setShowNewUser(true)}
          />
        )}

        {activeTab === 'stores' && <StoresTable stores={stores} loading={loading} />}

        {activeTab === 'activity' && <ActivityFeed activities={activities} loading={loading} />}
      </div>
    </main>
  );
}
