'use client';

import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
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
  critical: { icon: AlertTriangle, color: 'text-red-500', bg: 'bg-red-500/10', border: 'border-red-500/30' },
  warning: { icon: AlertCircle, color: 'text-amber-500', bg: 'bg-amber-500/10', border: 'border-amber-500/30' },
  info: { icon: Info, color: 'text-blue-500', bg: 'bg-blue-500/10', border: 'border-blue-500/30' },
  success: { icon: CheckCircle, color: 'text-emerald-500', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' },
};

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, isAuthenticated, logout, hasRole, hasPermission } = useAuth();
  
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const notificationRef = useRef<HTMLDivElement>(null);

  // SSE Connection for real-time notifications
  useEffect(() => {
    if (!isAuthenticated) return;

    let eventSource: EventSource | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;

    const connectSSE = () => {
      // Connect to alerts stream
      eventSource = new EventSource(`${API_URL}/stream/alerts`);

      eventSource.addEventListener('alert', (event) => {
        try {
          const alert = JSON.parse(event.data);
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
        } catch (e) {
          console.error('Failed to parse alert:', e);
        }
      });

      eventSource.onerror = () => {
        eventSource?.close();
        // Reconnect after 5 seconds
        reconnectTimeout = setTimeout(connectSSE, 5000);
      };
    };

    // Start SSE connection
    connectSSE();

    // Also fetch initial notifications
    const fetchInitialNotifications = async () => {
      try {
        const response = await fetch(`${API_URL}/api/alerts/recent?limit=10`);
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

    return () => {
      eventSource?.close();
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
    };
  }, [isAuthenticated]);

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
    <nav className="sticky top-0 z-50 bg-slate-900/80 backdrop-blur-xl border-b border-slate-700/50">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <ShoppingBag className="w-5 h-5 text-white" />
            </div>
            <div className="hidden md:block">
              <h1 className="text-lg font-bold text-white">Lulu Intelligence</h1>
              <p className="text-xs text-slate-400 -mt-1">UAE Analytics</p>
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
                    ? 'bg-slate-700/50 text-cyan-400'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
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
                className="relative p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-all"
              >
                <Bell className="w-5 h-5" />
                {unreadCount > 0 && (
                  <span className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-red-500 text-white text-xs font-bold flex items-center justify-center animate-pulse">
                    {unreadCount}
                  </span>
                )}
              </button>

              {/* Notification Dropdown Panel */}
              {notificationOpen && (
                <div className="absolute right-0 mt-2 w-96 bg-slate-800 rounded-xl border border-slate-700/50 shadow-2xl overflow-hidden z-50">
                  {/* Header */}
                  <div className="px-4 py-3 bg-slate-700/50 border-b border-slate-600/50 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Bell className="w-4 h-4 text-cyan-400" />
                      <span className="font-semibold text-white">Notifications</span>
                      {unreadCount > 0 && (
                        <span className="px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 text-xs font-medium">
                          {unreadCount} new
                        </span>
                      )}
                      {/* Live Streaming Indicator */}
                      <div className="flex items-center gap-1 ml-2">
                        <span className="relative flex h-2 w-2">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                        </span>
                        <span className="text-xs text-green-400 font-medium">LIVE</span>
                      </div>
                    </div>
                    {unreadCount > 0 && (
                      <button 
                        onClick={markAllAsRead}
                        className="text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
                      >
                        Mark all read
                      </button>
                    )}
                  </div>

                  {/* Notification List */}
                  <div className="max-h-96 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <div className="p-8 text-center">
                        <Bell className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                        <p className="text-slate-400">No notifications yet</p>
                      </div>
                    ) : (
                      notifications.map((notification) => {
                        const config = notificationConfig[notification.type];
                        const Icon = config.icon;
                        return (
                          <div
                            key={notification.id}
                            onClick={() => markAsRead(notification.id)}
                            className={`px-4 py-3 border-b border-slate-700/50 hover:bg-slate-700/30 cursor-pointer transition-all ${
                              !notification.read ? 'bg-slate-700/20' : ''
                            }`}
                          >
                            <div className="flex items-start gap-3">
                              <div className={`p-2 rounded-lg ${config.bg}`}>
                                <Icon className={`w-4 h-4 ${config.color}`} />
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <p className={`text-sm font-medium ${!notification.read ? 'text-white' : 'text-slate-300'}`}>
                                    {notification.title}
                                  </p>
                                  {!notification.read && (
                                    <span className="w-2 h-2 rounded-full bg-cyan-400"></span>
                                  )}
                                </div>
                                <p className="text-xs text-slate-400 mt-0.5 truncate">{notification.message}</p>
                                <div className="flex items-center gap-2 mt-1">
                                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium uppercase ${config.bg} ${config.color}`}>
                                    {notification.category}
                                  </span>
                                  <span className="text-[10px] text-slate-500">{notification.time}</span>
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>

                  {/* Footer */}
                  <div className="px-4 py-3 bg-slate-700/30 border-t border-slate-600/50">
                    <Link
                      href="/alerts"
                      onClick={() => setNotificationOpen(false)}
                      className="flex items-center justify-center gap-2 text-sm text-cyan-400 hover:text-cyan-300 transition-colors"
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
                className="flex items-center gap-3 px-3 py-2 rounded-xl bg-slate-800/50 hover:bg-slate-700/50 transition-all border border-slate-700/50"
              >
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center text-white font-semibold text-sm">
                  {user?.first_name?.[0]}{user?.last_name?.[0]}
                </div>
                <div className="hidden lg:block text-left">
                  <p className="text-sm font-medium text-white">
                    {user?.first_name} {user?.last_name}
                  </p>
                  <p className="text-xs text-slate-400">
                    {ROLE_DISPLAY_NAMES[user?.role as UserRole] || user?.role}
                  </p>
                </div>
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${userMenuOpen ? 'rotate-180' : ''}`} />
              </button>

              {/* Dropdown Menu */}
              {userMenuOpen && (
                <div className="absolute right-0 mt-2 w-64 py-2 bg-slate-800 rounded-xl border border-slate-700/50 shadow-xl">
                  {/* User Info */}
                  <div className="px-4 py-3 border-b border-slate-700/50">
                    <p className="text-sm font-medium text-white">
                      {user?.first_name} {user?.last_name}
                    </p>
                    <p className="text-xs text-slate-400 truncate">{user?.email}</p>
                    <div className="mt-2 flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        user?.role === 'super_admin' ? 'bg-purple-500/20 text-purple-400' :
                        user?.role === 'regional_manager' ? 'bg-cyan-500/20 text-cyan-400' :
                        user?.role === 'store_manager' ? 'bg-emerald-500/20 text-emerald-400' :
                        'bg-slate-500/20 text-slate-400'
                      }`}>
                        {ROLE_DISPLAY_NAMES[user?.role as UserRole] || user?.role}
                      </span>
                    </div>
                  </div>

                  {/* Accessible Stores Info */}
                  <div className="px-4 py-2 border-b border-slate-700/50">
                    <p className="text-xs text-slate-500 mb-1">Access Level</p>
                    <div className="flex items-center gap-2 text-xs">
                      <Store className="w-3 h-3 text-slate-400" />
                      <span className="text-slate-300">
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
                      className="flex items-center gap-3 px-4 py-2 text-sm text-slate-300 hover:text-white hover:bg-slate-700/50 transition-colors"
                      onClick={() => setUserMenuOpen(false)}
                    >
                      <User className="w-4 h-4" />
                      Profile Settings
                    </Link>
                    <Link
                      href="/settings"
                      className="flex items-center gap-3 px-4 py-2 text-sm text-slate-300 hover:text-white hover:bg-slate-700/50 transition-colors"
                      onClick={() => setUserMenuOpen(false)}
                    >
                      <Settings className="w-4 h-4" />
                      Preferences
                    </Link>
                  </div>

                  {/* Logout */}
                  <div className="pt-1 border-t border-slate-700/50">
                    <button
                      onClick={handleLogout}
                      className="flex items-center gap-3 w-full px-4 py-2 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors"
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
              className="md:hidden p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 transition-all"
            >
              {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Navigation */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-slate-700/50 bg-slate-900/95 backdrop-blur-xl">
          <div className="px-4 py-4 space-y-2">
            {filteredNavItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileMenuOpen(false)}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${
                  pathname === item.href
                    ? 'bg-slate-700/50 text-cyan-400'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
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
