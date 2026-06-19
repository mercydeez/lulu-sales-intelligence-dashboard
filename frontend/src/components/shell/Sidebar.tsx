'use client';

import { ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { cn } from '@/lib/cn';
import {
  LayoutDashboard,
  Package,
  BarChart3,
  Bell,
  Settings,
  Store,
  Tag,
  FileText,
  Shield,
  X,
  ShoppingBag,
  Activity,
  Users,
  Database,
  Brain,
} from 'lucide-react';
import { UserRole } from '@/types/auth';

interface NavItem {
  label: string;
  tKey: string;
  href: string;
  icon: ReactNode;
  roles?: UserRole[];
  permission?: string;
}

export const navItems: NavItem[] = [
  { label: 'Dashboard', tKey: 'nav.dashboard', href: '/', icon: <LayoutDashboard className="w-5 h-5" /> },
  { label: 'Inventory', tKey: 'nav.inventory', href: '/inventory', icon: <Package className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Promotions', tKey: 'nav.promotions', href: '/promotions', icon: <Tag className="w-5 h-5" />, permission: 'can_manage_promotions' },
  { label: 'Analytics', tKey: 'nav.analytics', href: '/analytics', icon: <BarChart3 className="w-5 h-5" /> },
  { label: 'Forecast Lab', tKey: 'nav.forecastLab', href: '/forecast-lab', icon: <Brain className="w-5 h-5" /> },
  { label: 'Employees', tKey: 'nav.employees', href: '/employees', icon: <Users className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Reports', tKey: 'nav.reports', href: '/reports', icon: <FileText className="w-5 h-5" />, permission: 'can_export' },
  { label: 'Alerts', tKey: 'nav.alerts', href: '/alerts', icon: <Bell className="w-5 h-5" /> },
  { label: 'Admin', tKey: 'nav.admin', href: '/admin', icon: <Shield className="w-5 h-5" />, roles: ['super_admin'] },
  { label: 'Data Sources', tKey: 'nav.dataSources', href: '/data-sources', icon: <Database className="w-5 h-5" />, roles: ['super_admin'] },
  { label: 'Monitoring', tKey: 'nav.monitoring', href: '/monitoring', icon: <Activity className="w-5 h-5" />, permission: 'is_admin' },
];

export interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { hasRole, hasPermission } = useAuth();
  const { t } = useLanguage();

  const canAccessItem = (item: NavItem): boolean => {
    if (item.roles && !hasRole(item.roles)) return false;
    if (item.permission && !hasPermission(item.permission)) return false;
    return true;
  };

  const filteredNavItems = navItems.filter(canAccessItem);

  return (
    <div className="flex flex-col h-full">
      <Link href="/" onClick={onNavigate} className="flex items-center gap-3 px-5 h-16 shrink-0 border-b border-coral-100">
        <div className="w-10 h-10 rounded-xl sunset-gradient flex items-center justify-center shadow-sunset shrink-0">
          <ShoppingBag className="w-5 h-5 text-white" />
        </div>
        <div className="min-w-0">
          <h1 className="text-base font-bold gradient-text truncate">Lulu Intelligence</h1>
          <p className="text-xs text-ink-muted -mt-0.5">UAE Analytics</p>
        </div>
      </Link>

      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
        {filteredNavItems.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all',
                active ? 'bg-coral-100 text-coral-600' : 'text-ink-muted hover:text-ink hover:bg-coral-50'
              )}
            >
              {item.icon}
              {t(item.tKey)}
            </Link>
          );
        })}
      </nav>

      <div className="px-3 py-4 border-t border-coral-100 space-y-1">
        <Link
          href="/settings"
          onClick={onNavigate}
          className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-ink-muted hover:text-ink hover:bg-coral-50 transition-all"
        >
          <Settings className="w-5 h-5" />
          Preferences
        </Link>
      </div>
    </div>
  );
}

/** Desktop fixed rail + mobile off-canvas drawer, sharing the same nav content. */
export function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  return (
    <>
      <aside className="hidden lg:flex lg:flex-col lg:fixed lg:inset-y-0 lg:start-0 lg:w-64 bg-white/85 backdrop-blur-xl border-e border-coral-100 z-30">
        <SidebarContent />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm animate-fade-in" onClick={onClose} />
          <aside className="absolute inset-y-0 start-0 w-72 bg-white shadow-2xl flex flex-col animate-slide-in">
            <button
              onClick={onClose}
              className="absolute top-4 end-4 p-1.5 rounded-full text-ink-muted hover:text-ink hover:bg-coral-50 transition-colors"
            >
              <X className="w-4 h-4" />
         