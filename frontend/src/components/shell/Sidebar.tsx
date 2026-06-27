'use client';

import { ReactNode, useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { cn } from '@/lib/cn';
import { PRODUCT_NAME } from '@/lib/brand';
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
  Truck,
  Code2,
  Inbox,
  Lightbulb,
  ShieldAlert,
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
  { label: 'Procurement', tKey: 'nav.procurement', href: '/procurement', icon: <Truck className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Approvals', tKey: 'nav.approvals', href: '/approvals', icon: <Inbox className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Analytics', tKey: 'nav.analytics', href: '/analytics', icon: <BarChart3 className="w-5 h-5" /> },
  { label: 'Insights', tKey: 'nav.insights', href: '/insights', icon: <Lightbulb className="w-5 h-5" /> },
  { label: 'Forecast Lab', tKey: 'nav.forecastLab', href: '/forecast-lab', icon: <Brain className="w-5 h-5" /> },
  { label: 'Employees', tKey: 'nav.employees', href: '/employees', icon: <Users className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Reports', tKey: 'nav.reports', href: '/reports', icon: <FileText className="w-5 h-5" />, permission: 'can_export' },
  { label: 'Alerts', tKey: 'nav.alerts', href: '/alerts', icon: <Bell className="w-5 h-5" /> },
  { label: 'Admin', tKey: 'nav.admin', href: '/admin', icon: <Shield className="w-5 h-5" />, roles: ['super_admin'] },
  { label: 'Security', tKey: 'nav.security', href: '/security', icon: <ShieldAlert className="w-5 h-5" />, roles: ['super_admin'] },
  { label: 'Data Sources', tKey: 'nav.dataSources', href: '/data-sources', icon: <Database className="w-5 h-5" />, roles: ['super_admin'] },
  { label: 'Developers', tKey: 'nav.developers', href: '/developers', icon: <Code2 className="w-5 h-5" />, roles: ['super_admin'] },
  { label: 'Monitoring', tKey: 'nav.monitoring', href: '/monitoring', icon: <Activity className="w-5 h-5" />, permission: 'is_admin' },
];

export interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { hasRole, hasPermission, authFetch, isAuthenticated } = useAuth();
  const { t } = useLanguage();

  // Live critical-alert count for the Alerts nav badge (same source the
  // dashboard uses for its alert tiles — /api/inventory/summary).
  const [criticalCount, setCriticalCount] = useState(0);
  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    (async () => {
      try {
        const res = await authFetch('/api/inventory/summary');
        if (!res.ok) return;
        const data = await res.json();
        if (active) setCriticalCount(data.out_of_stock_count ?? 0);
      } catch {
        // leave badge hidden on failure
      }
    })();
    return () => { active = false; };
  }, [isAuthenticated, authFetch]);

  // Live count of active security threats (24h) for the Security nav badge.
  const [threatCount, setThreatCount] = useState(0);
  useEffect(() => {
    if (!isAuthenticated || !hasRole(['super_admin'])) return;
    let active = true;
    const poll = async () => {
      try {
        const res = await authFetch('/api/security/kpi');
        if (!res.ok) return;
        const data = await res.json();
        if (active) setThreatCount(data.threats_active ?? 0);
      } catch {
        /* leave badge hidden on failure */
      }
    };
    poll();
    const id = setInterval(poll, 30000);
    return () => { active = false; clearInterval(id); };
  }, [isAuthenticated, authFetch, hasRole]);

  // Live count of POs awaiting approval for the Approvals nav badge.
  const [approvalCount, setApprovalCount] = useState(0);
  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    (async () => {
      try {
        const res = await authFetch('/api/procurement/approvals');
        if (!res.ok) return;
        const data = await res.json();
        if (active) setApprovalCount(data.count ?? 0);
      } catch {
        // leave badge hidden on failure
      }
    })();
    return () => { active = false; };
  }, [isAuthenticated, authFetch, pathname]);

  const canAccessItem = (item: NavItem): boolean => {
    if (item.roles && !hasRole(item.roles)) return false;
    if (item.permission && !hasPermission(item.permission)) return false;
    return true;
  };

  const filteredNavItems = navItems.filter(canAccessItem);

  return (
    <div className="flex flex-col h-full">
      <Link href="/" onClick={onNavigate} className="flex items-center gap-3 px-5 h-16 shrink-0 border-b border-line">
        <div className="w-10 h-10 rounded-xl sunset-gradient flex items-center justify-center shadow-sunset shrink-0">
          <ShoppingBag className="w-5 h-5 text-white" />
        </div>
        <div className="min-w-0">
          <h1 className="text-base font-bold gradient-text truncate">{PRODUCT_NAME}</h1>
          <p className="text-xs text-ink-muted -mt-0.5">Retail Analytics</p>
        </div>
      </Link>

      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
        {filteredNavItems.map((item) => {
          const active = pathname === item.href;
          const showBadge = item.href === '/alerts' && criticalCount > 0;
          const showApprovals = item.href === '/approvals' && approvalCount > 0;
          const showThreats = item.href === '/security' && threatCount > 0;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors',
                active ? 'text-teal-700' : 'text-ink-muted hover:text-ink hover:bg-surface-2'
              )}
            >
              {/* Animated active indicator — slides between items via shared layoutId. */}
              {active && (
                <motion.span
                  layoutId="nav-active"
                  className="absolute inset-0 rounded-xl bg-teal-50 ring-1 ring-teal-100"
                  transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                />
              )}
              {active && (
                <motion.span
                  layoutId="nav-active-bar"
                  className="absolute start-0 top-1/2 -translate-y-1/2 h-5 w-1 rounded-full bg-teal-600"
                  transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                />
              )}
              <span className="relative z-10 flex items-center">{item.icon}</span>
              <span className="relative z-10 flex-1">{t(item.tKey)}</span>
              {showBadge && (
                <span className="relative z-10 ms-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1.5 rounded-full bg-rose-600 text-white text-[10px] font-bold">
                  {criticalCount}
                </span>
              )}
              {showApprovals && (
                <span className="relative z-10 ms-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1.5 rounded-full bg-teal-500 text-white text-[10px] font-bold">
                  {approvalCount}
                </span>
              )}
              {showThreats && (
                <span className="relative z-10 ms-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1.5 rounded-full bg-rose-600 text-white text-[10px] font-bold">
                  {threatCount}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="px-3 py-4 border-t border-line space-y-1">
        <Link
          href="/settings"
          onClick={onNavigate}
          className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-ink-muted hover:text-ink hover:bg-surface-2 transition-all"
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
      <aside className="hidden lg:flex lg:flex-col lg:fixed lg:inset-y-0 lg:start-0 lg:w-64 bg-surface border-e border-line z-30">
        <SidebarContent />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm animate-fade-in" onClick={onClose} />
          <aside className="absolute inset-y-0 start-0 w-72 bg-surface shadow-2xl flex flex-col animate-slide-in">
            <button
              onClick={onClose}
              className="absolute top-4 end-4 p-1.5 rounded-full text-ink-muted hover:text-ink hover:bg-surface-2 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
            <SidebarContent onNavigate={onClose} />
          </aside>
        </div>
      )}
    </>
  );
}
