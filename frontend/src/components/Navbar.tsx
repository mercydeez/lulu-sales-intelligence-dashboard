'use client';

import { useState, useRef, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useEventStream } from '@/hooks/useEventStream';
import { Badge } from '@/components/ui';
import {
  LayoutDashboard,
  Package,
  BarChart3,
  Bell,
  Settings,
  LogOut,
  ChevronDown,
  User,
  Store,
  Tag,
  FileText,
  Shield,
  Menu,
  X,
  ShoppingBag,
  Activity,
  AlertTriangle,
  AlertCircle,
  Info,
  CheckCircle,
  ChevronRight,

  Users
} from 'lucide-react';
import { ROLE_DISPLAY_NAMES, UserRole } from '@/types/auth';
import { ReactNode } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface NavItem {
  label: string;
  href: string;
  icon: ReactNode;
  roles?: UserRole[];
  permission?: string;
}

interface NotificationItem {
  id: number;
  title: string;
  message: string;
  type: 'critical' | 'warning' | 'info' | 'success';
  category: 'inventory' | 'sales' | 'system' | 'promotion';
  time: string;
  read: boolean;
}

const navItems: NavItem[] = [
  {
    label: 'Dashboard',
    href: '/',
    icon: <LayoutDashboard className="w-5 h-5" />
  },
  {
    label: 'Inventory',
    href: '/inventory',
    icon: <Package className="w-5 h-5" />,
    permission: 'can_manage_inventory'
  },
  {
    label: 'Promotions',
    href: '/promotions',
    icon: <Tag className="w-5 h-5" />,
    permission: 'can_manage_promotions'
  },
  {
    label: 'Analytics',
    href: '/analytics',
    icon: <BarChart3 className="w-5 h-5" />
  },
  {
    label: 'Employees',
    href: '/employees',
    icon: <Users className="w-5 h-5" />,
    permission: 'can_manage_inventory'
  },
  {
    label: 'Reports',
    href: '/reports',
    icon: <FileText className="w-5 h-5" />,
    permission: 'can_export'
  },
  {
    label: 'Alerts',
    href: '/alerts',
    icon: <Bell className="w-5 h-5" />
  },
  {
    label: 'Admin',
    href: '/admin',
    icon: <Shield className="w-5 h-5" />,
    roles: ['super_admin']
  },
  {
    label: 'Monitoring',
    href: '/monitoring',
    icon: <Activity className="w-5 h-5" />,
    permission: 'is_admin'
  }
];

// Notification type config
const notificationConfig = {
  critical: { icon: AlertTriangle, color: 'text-rose-600', bg: 'bg-rose-100', border: 'border-rose-200' },
  warning: { icon: AlertCircle, color: 'text-amber-600', bg: 'bg-amber-100', border: 'border-amber-200' },
  info: { icon: Info, color: 'text-violet-600', bg: 'bg-violet-100', border: 'border-violet-200' },
  success: { icon: CheckCircle, color: 'text-emerald-600', bg: 'bg-emerald-100', border: 'border-emerald-200' },
};

const roleBadgeVariant: Record<string, 'violet' | 'teal' | 'coral' | 'neutral'> = {
  super_admin: 'violet',
  regional_manager: 'teal',
  store_manager: 'coral',
};

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isAuthenticated, logout, hasRole, hasPermission, authFetch } = useAuth();

  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const notificationRef = useRef<HTMLDivElement>(null);

  // Connect to SSE using useEventStream hook
  const eventHandlers = useMemo(() => ({
    alert: (alert: any) => {
      const newNotification: NotificationItem = {
        id: alert.id,
        title: alert.title,
        message: alert.message,
        type: alert.severity === 'critical' ? 'critical' :
              alert.severity === 'warning' ? 'warning' :
              alert.severity === 'success' ? 'success' : 'info',
        category: alert.category || 'inventory',
        time: 'Just now',
        read: false,
      };

      setNotifications(prev => {
        // Avoid duplicates and keep max 15 notifications
        const exists = prev.some(n => n.id === newNotification.id);
        if (exists) return prev;
        return [newNotification, ...prev].slice(0, 15);
      });
    }
  }), []);

  useEventStream(isAuthenticated ? '/stream/alerts' : null, { eventHandlers });

  // Fetch initial notifications
  useEffect(() => {
    if (!isAuthenticated) return;

    const fetchInitialNotifications = async () => {
      try {
        const response = await authFetch('/api/alerts/recent?limit=10');
        if (response.ok) {
          const data = await response.json();
          const apiNotifications = (data.alerts || []).map((alert: any) => ({
            id: alert.id,
            title: alert.title,
            message: alert.message,
            type: alert.severity === 'critical' ? 'critical' : alert.severity === 'warning' ? 'warning' : 'info',
            category: alert.alert_type || 'inventory',
            time: alert.time_ago || 'Recently',
            read: alert.status !== 'active'
          }));
          setNotifications(prev => {
            const merged = [...prev, ...apiNotifications];
            // Deduplicate by id
            const unique = merged.filter((n, i, arr) => arr.findIndex(x => x.id === n.id) === i);
            return unique.slice(0, 15);
          });
        }
      } catch (error) {
        console.error('Failed to fetch initial notifications:', error);
      }
    };

    fetchInitialNotifications();
  }, [isAuthenticated, authFetch]);

  const unreadCount = notifications.filter(n => !n.read).length;

  // Close menus when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
      if (notificationRef.current && !notificationRef.current.contains(event.target as Node)) {
        setNotificationOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const markAsRead = (id: number) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
  };

  const markAllAsRead = () => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
  };

  const handleLogout = async () => {
    await logout();
    router.push('/login');
  };

  const canAccessItem = (item: NavItem): boolean => {
    if (item.roles && !hasRole(item.roles)) return false;
    if (item.permission && !hasPermission(item.permission)) return false;
    return true;
  };

  if (!isAuthenticated) return null;

  const filteredNavItems = navItems.filter(canAccessItem);

  return (
    <nav className="sticky top-0 z-50 bg-white/85 backdrop-blur-xl border-b border-coral-100">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl sunset-gradient flex items-center justify-center shadow-sunset">
              <ShoppingBag className="w-5 h-5 text-white" />
            </div>
            <div className="hidden md:block">
              <h1 className="text-lg font-bold gradient-text">Lulu Intelligence</h1>
              <p className="text-xs text-ink-muted -mt-1">UAE Analytics</p>
            </div>
          </Link>

          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center gap-1">
            {filteredNavItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
                  pathname === item.href
                    ? 'bg-coral-100 text-coral-600'
                    : 'text-ink-muted hover:text-ink hover:bg-coral-50'
                }`}
              >
                {item.icon}
                <span className="text-sm font-medium">{item.label}</span>
              </Link>
            ))}
          </div>

          {/* Right side */}
          <div className="flex items-center gap-3">
            {/* Notifications Button & Panel */}
            <div className="relative" ref={notificationRef}>
              <button
                onClick={() => setNotificationOpen(!notificationOpen)}
                className="relative p-2 rounded-lg text-ink-muted hover:text-ink hover:bg-coral-50 transition-all"
              >
                <Bell className="w-5 h-5" />
                {unreadCount > 0 && (
                  <span className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-rose-500 text-white text-xs font-bold flex items-center justify-center animate-pulse">
                    {unreadCount}
                  </span>
                )}
              </button>

              {/* Notification Dropdown Panel */}
              {notificationOpen && (
                <div className="absolute right-0 mt-2 w-96 glass-strong rounded-xl shadow-2xl overflow-hidden z-50">
                  {/* Header */}
                  <div className="px-4 py-3 bg-coral-50/80 border-b border-coral-100 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Bell className="w-4 h-4 text-coral-500" />
                      <span className="font-semibold text-ink">Notifications</span>
                      {unreadCount > 0 && (
                        <span className="px-2 py-0.5 rounded-full bg-rose-100 text-rose-600 text-xs font-medium">
                          {unreadCount} new
                        </span>
                      )}
                      {/* Live Streaming Indicator */}
                      <div className="flex items-center gap-1 ml-2">
                        <span className="relative flex h-2 w-2">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-teal-500"></span>
                        </span>
                        <span className="text-xs text-teal-600 font-medium">LIVE</span>
                      </div>
                    </div>
                    {unreadCount > 0 && (
                      <button
                        onClick={markAllAsRead}
                        className="text-xs text-violet-600 hover:text-coral-500 transition-colors"
                      >
                        Mark all read
                      </button>
                    )}
                  </div>

                  {/* Notification List */}
                  <div className="max-h-96 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <div className="p-8 text-center">
                        <Bell className="w-12 h-12 text-coral-200 mx-auto mb-3" />
                        <p className="text-ink-muted">No notifications yet</p>
                      </div>
                    ) : (
                      notifications.map((notification) => {
                        const config = notificationConfig[notification.type];
                        const Icon = config.icon;
                        return (
                          <div
                            key={notification.id}
                            onClick={() => markAsRead(notification.id)}
                            className={`px-4 py-3 border-b border-coral-100 hover:bg-coral-50/60 cursor-pointer transition-all ${
                              !notification.read ? 'bg-coral-50/40' : ''
                            }`}
                          >
                            <div className="flex items-start gap-3">
                              <div className={`p-2 rounded-lg ${config.bg}`}>
                                <Icon className={`w-4 h-4 ${config.color}`} />
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <p className={`text-sm font-medium ${!notification.read ? 'text-ink' : 'text-ink-soft'}`}>
                                    {notification.title}
                                  </p>
                                  {!notification.read && (
                                    <span className="w-2 h-2 rounded-full bg-coral-500"></span>
                                  )}
                                </div>
                                <p className="text-xs text-ink-muted mt-0.5 truncate">{notification.message}</p>
                                <div className="flex items-center gap-2 mt-1">
                                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium uppercase ${config.bg} ${config.color}`}>
                                    {notification.category}
                                  </span>
                                  <span className="text-[10px] text-ink-muted/80">{notification.time}</span>
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>

                  {/* Footer */}
                  <div className="px-4 py-3 bg-coral-50/60 border-t border-coral-100">
                    <Link
                      href="/alerts"
                      onClick={() => setNotificationOpen(false)}
                      className="flex items-center justify-center gap-2 text-sm text-violet-600 hover:text-coral-500 transition-colors"
                    >
                      <span>View all alerts</span>
                      <ChevronRight className="w-4 h-4" />
                    </Link>
                  </div>
                </div>
              )}
            </div>

            {/* User Menu */}
            <div className="relative" ref={userMenuRef}>
              <button
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                className="flex items-center gap-3 px-3 py-2 rounded-xl bg-coral-50 hover:bg-coral-100 transition-all border border-coral-100"
              >
                <div className="w-8 h-8 rounded-lg sunset-gradient flex items-center justify-center text-white font-semibold text-sm">
                  {user?.first_name?.[0]}{user?.last_name?.[0]}
                </div>
                <div className="hidden lg:block text-left">
                  <p className="text-sm font-medium text-ink">
                    {user?.first_name} {user?.last_name}
                  </p>
                  <p className="text-xs text-ink-muted">
                    {ROLE_DISPLAY_NAMES[user?.role as UserRole] || user?.role}
                  </p>
                </div>
                <ChevronDown className={`w-4 h-4 text-ink-muted transition-transform ${userMenuOpen ? 'rotate-180' : ''}`} />
              </button>

              {/* Dropdown Menu */}
              {userMenuOpen && (
                <div className="absolute right-0 mt-2 w-64 py-2 glass-strong rounded-xl shadow-xl">
                  {/* User Info */}
                  <div className="px-4 py-3 border-b border-coral-100">
                    <p className="text-sm font-medium text-ink">
                      {user?.first_name} {user?.last_name}
                    </p>
                    <p className="text-xs text-ink-muted truncate">{user?.email}</p>
                    <div className="mt-2 flex items-center gap-2">
                      <Badge variant={roleBadgeVariant[user?.role as string] || 'neutral'} size="sm">
                        {ROLE_DISPLAY_NAMES[user?.role as UserRole] || user?.role}
                      </Badge>
                    </div>
                  </div>

                  {/* Accessible Stores Info */}
                  <div className="px-4 py-2 border-b border-coral-100">
                    <p className="text-xs text-ink-muted mb-1">Access Level</p>
                    <div className="flex items-center gap-2 text-xs">
                      <Store className="w-3 h-3 text-ink-muted" />
                      <span className="text-ink-soft">
                        {user?.role === 'super_admin'
                          ? 'All Stores'
                          : `${user?.accessible_stores?.length || 0} store(s)`}
                      </span>
                    </div>
                  </div>

                  {/* Menu Items */}
                  <div className="py-1">
                    <Link
                      href="/profile"
                      className="flex items-center gap-3 px-4 py-2 text-sm text-ink-soft hover:text-ink hover:bg-coral-50 transition-colors"
                      onClick={() => setUserMenuOpen(false)}
                    >
                      <User className="w-4 h-4" />
                      Profile Settings
                    </Link>
                    <Link
                      href="/settings"
                      className="flex items-center gap-3 px-4 py-2 text-sm text-ink-soft hover:text-ink hover:bg-coral-50 transition-colors"
                      onClick={() => setUserMenuOpen(false)}
                    >
                      <Settings className="w-4 h-4" />
                      Preferences
                    </Link>
                  </div>

                  {/* Logout */}
                  <div className="pt-1 border-t border-coral-100">
                    <button
                      onClick={handleLogout}
                      className="flex items-center gap-3 w-full px-4 py-2 text-sm text-rose-600 hover:text-rose-700 hover:bg-rose-50 transition-colors"
                    >
                      <LogOut className="w-4 h-4" />
                      Sign Out
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Mobile Menu Button */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="md:hidden p-2 rounded-lg text-ink-muted hover:text-ink hover:bg-coral-50 transition-all"
            >
              {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Navigation */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-coral-100 bg-white/95 backdrop-blur-xl">
          <div className="px-4 py-4 space-y-2">
            {filteredNavItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileMenuOpen(false)}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${
                  pathname === item.href
                    ? 'bg-coral-100 text-coral-600'
                    : 'text-ink-muted hover:text-ink hover:bg-coral-50'
                }`}
              >
                {item.icon}
                <span className="font-medium">{item.label}</span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </nav>
  );
}
