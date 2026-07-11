/**
 * Central navigation config — the single, append-only place that lists every
 * sidebar destination and the icon map used by the server-driven nav manifest.
 *
 * WHY THIS FILE EXISTS (parallel-development / merge-conflict reduction):
 * Previously every new page edited `components/shell/Sidebar.tsx` — the 200-line
 * component with all the badge-count effects — just to add a `navItems` entry and
 * an icon. With three developers adding pages in parallel that made Sidebar a
 * merge-conflict hub. Now Sidebar (and CommandPalette) import from here; adding a
 * page is a ONE-LINE append to `navItems` below.
 *
 * HOW TO ADD A NAV ENTRY:
 *   1. Import the lucide icon you need below.
 *   2. Append one `{ label, tKey, href, icon, roles?/permission? }` to `navItems`.
 *   3. Add the matching `tKey` to LanguageContext (both `en` and `ar`).
 *
 * OWNERSHIP: Yash is steward of this file (see TEAM_OWNERSHIP.md). Feature owners
 * append their own entry; keep additions grouped near related routes.
 */
import { ReactNode } from 'react';
import {
  LayoutDashboard,
  Package,
  BarChart3,
  Bell,
  Store,
  Tag,
  FileText,
  Shield,
  Activity,
  Users,
  Database,
  Brain,
  Truck,
  Code2,
  Inbox,
  Lightbulb,
  ShieldAlert,
  ScrollText,
  Wand2,
  UploadCloud,
  TrendingUp,
  MapPin,
  Sunrise,
  Scale,
  ClipboardCheck,
  SlidersHorizontal,
} from 'lucide-react';
import { UserRole } from '@/types/auth';

export interface NavItem {
  label: string;
  tKey: string;
  href: string;
  icon: ReactNode;
  roles?: UserRole[];
  permission?: string;
}

export const navItems: NavItem[] = [
  { label: 'Dashboard', tKey: 'nav.dashboard', href: '/', icon: <LayoutDashboard className="w-5 h-5" /> },
  { label: 'Briefing', tKey: 'nav.briefing', href: '/briefing', icon: <Sunrise className="w-5 h-5" /> },
  { label: 'Role Workbench', tKey: 'nav.roleWorkbench', href: '/role-workbench', icon: <ClipboardCheck className="w-5 h-5" /> },
  { label: 'Decisions', tKey: 'nav.decisions', href: '/decisions', icon: <Scale className="w-5 h-5" /> },
  { label: 'Inventory', tKey: 'nav.inventory', href: '/inventory', icon: <Package className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Promotions', tKey: 'nav.promotions', href: '/promotions', icon: <Tag className="w-5 h-5" />, permission: 'can_manage_promotions' },
  { label: 'Procurement', tKey: 'nav.procurement', href: '/procurement', icon: <Truck className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Approvals', tKey: 'nav.approvals', href: '/approvals', icon: <Inbox className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Value', tKey: 'nav.value', href: '/value', icon: <TrendingUp className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Analytics', tKey: 'nav.analytics', href: '/analytics', icon: <BarChart3 className="w-5 h-5" /> },
  { label: 'Insights', tKey: 'nav.insights', href: '/insights', icon: <Lightbulb className="w-5 h-5" /> },
  { label: 'Sage Copilot', tKey: 'nav.sageCopilot', href: '/copilot', icon: <Lightbulb className="w-5 h-5" />, roles: ['super_admin'] },
  { label: 'Action Drafts', tKey: 'nav.actionDrafts', href: '/action-drafts', icon: <Wand2 className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Forecast Lab', tKey: 'nav.forecastLab', href: '/forecast-lab', icon: <Brain className="w-5 h-5" /> },
  { label: 'UAE Insights', tKey: 'nav.uaeInsights', href: '/uae-insights', icon: <MapPin className="w-5 h-5" /> },
  { label: 'Employees', tKey: 'nav.employees', href: '/employees', icon: <Users className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Reports', tKey: 'nav.reports', href: '/reports', icon: <FileText className="w-5 h-5" />, permission: 'can_export' },
  { label: 'Alerts', tKey: 'nav.alerts', href: '/alerts', icon: <Bell className="w-5 h-5" /> },
  { label: 'Admin', tKey: 'nav.admin', href: '/admin', icon: <Shield className="w-5 h-5" />, roles: ['super_admin', 'regional_manager'] },
  { label: 'Security', tKey: 'nav.security', href: '/security', icon: <ShieldAlert className="w-5 h-5" />, roles: ['super_admin', 'regional_manager'] },
  { label: 'Audit', tKey: 'nav.audit', href: '/audit', icon: <ScrollText className="w-5 h-5" />, roles: ['super_admin', 'regional_manager'] },
  { label: 'Import Data', tKey: 'nav.imports', href: '/imports', icon: <UploadCloud className="w-5 h-5" />, permission: 'can_manage_inventory' },
  { label: 'Data Sources', tKey: 'nav.dataSources', href: '/data-sources', icon: <Database className="w-5 h-5" />, roles: ['super_admin', 'regional_manager'] },
  { label: 'Developers', tKey: 'nav.developers', href: '/developers', icon: <Code2 className="w-5 h-5" />, roles: ['super_admin', 'regional_manager'] },
  // Platform Console (internal): this roles gate is only the fallback-nav
  // visibility floor — Sidebar force-appends the item for any user with
  // `is_platform_developer`, and the page itself gates on that flag.
  { label: 'Platform Console', tKey: 'nav.platformConsole', href: '/platform-console', icon: <SlidersHorizontal className="w-5 h-5" />, roles: ['super_admin', 'regional_manager', 'store_manager'] },
  { label: 'Monitoring', tKey: 'nav.monitoring', href: '/monitoring', icon: <Activity className="w-5 h-5" />, permission: 'is_admin' },
];

// Role Experience Engine (Wave 1): the server nav manifest names icons as
// strings — resolve them here. Unknown icon names degrade to LayoutDashboard.
export const NAV_ICONS: Record<string, ReactNode> = {
  Sunrise: <Sunrise className="w-5 h-5" />,
  Scale: <Scale className="w-5 h-5" />,
  ClipboardCheck: <ClipboardCheck className="w-5 h-5" />,
  Store: <Store className="w-5 h-5" />,
  Bell: <Bell className="w-5 h-5" />,
  Inbox: <Inbox className="w-5 h-5" />,
  BarChart3: <BarChart3 className="w-5 h-5" />,
  Package: <Package className="w-5 h-5" />,
  Truck: <Truck className="w-5 h-5" />,
  Lightbulb: <Lightbulb className="w-5 h-5" />,
  TrendingUp: <TrendingUp className="w-5 h-5" />,
  FileText: <FileText className="w-5 h-5" />,
  LayoutDashboard: <LayoutDashboard className="w-5 h-5" />,
};
