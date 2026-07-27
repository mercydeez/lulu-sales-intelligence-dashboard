'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import Link from 'next/link';
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Boxes,
  Briefcase,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  PackageCheck,
  PackageSearch,
  RefreshCw,
  Scale,
  ShieldCheck,
  Sparkles,
  Store,
  Truck,
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { Button, Badge, Card, ErrorState, SkeletonCard, Stagger, RevealItem, Tabs } from '@/components/ui';
import { apiGet } from '@/lib/apiClient';
import { ROLE_DISPLAY_NAMES, type UserRole } from '@/types/auth';

type PersonaKey = 'senior_vp' | 'store_manager' | 'storekeeper';

interface Kpis {
  total_revenue_week?: number;
  total_revenue_today?: number;
  total_sales_today?: number;
  total_sales_week?: number;
  revenue_trend?: string;
}

interface DecisionsSummary {
  pending?: number;
  at_stake_aed_per_week?: number;
}

interface InventorySummary {
  out_of_stock_count?: number;
  low_stock_count?: number;
  overstocked_count?: number;
}

interface ApprovalsSummary {
  count?: number;
}

interface WorkbenchData {
  kpis: Kpis | null;
  decisions: DecisionsSummary | null;
  inventory: InventorySummary | null;
  approvals: ApprovalsSummary | null;
}

interface MetricSpec {
  label: string;
  value: (data: WorkbenchData) => string;
  hint: string;
}

interface ActionSpec {
  title: string;
  detail: string;
  href: string;
  icon: ReactNode;
  priority: 'Now' | 'Next' | 'Watch';
}

interface RoleSpec {
  key: PersonaKey;
  label: string;
  subtitle: string;
  mission: string;
  auditVerdict: string;
  scope: string;
  primaryQuestion: string;
  owner: string;
  currentGap: string;
  newFeature: string;
  badge: 'violet' | 'teal' | 'amber';
  metrics: MetricSpec[];
  actions: ActionSpec[];
  checks: string[];
  deepLinks: { label: string; href: string; icon: ReactNode }[];
}

const AED = (n: number | null | undefined, dp = 0) =>
  n == null ? '—' : `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: dp, minimumFractionDigits: dp })}`;

const count = (n: number | null | undefined, suffix = '') =>
  n == null ? '—' : `${n.toLocaleString('en-AE')}${suffix}`;

const trendLabel = (trend?: string) => {
  if (trend === 'up') return 'Up';
  if (trend === 'down') return 'Down';
  if (trend === 'stable') return 'Stable';
  return 'Reading';
};

const ROLE_SPECS: RoleSpec[] = [
  {
    key: 'senior_vp',
    label: 'Senior VP',
    subtitle: 'Chain command, money-first',
    mission: 'Know business health in five minutes, make the one decision only leadership can make, and leave operations routed.',
    auditVerdict: 'Current frontend is strong but still exposes too much module detail to executives. This lane reduces it to health, risk, growth, and decisions.',
    scope: 'All stores',
    primaryQuestion: 'Is the business healthy, and what is my one call today?',
    owner: 'Executive leadership',
    currentGap: 'Senior leaders can reach every screen, but the workflow is not opinionated enough for quick judgment.',
    newFeature: 'Executive command lane with live AED, pending decision load, cost at stake, and direct links to briefings and measured outcomes.',
    badge: 'violet',
    metrics: [
      { label: 'Revenue 7d', value: (d) => AED(d.kpis?.total_revenue_week), hint: 'Value metric, derived AED' },
      { label: 'Volume 7d', value: (d) => count(d.kpis?.total_sales_week, ' units'), hint: 'Volume only, not currency' },
      { label: 'Decisions', value: (d) => count(d.decisions?.pending), hint: 'Open items routed by Sage' },
      { label: 'At stake /wk', value: (d) => AED(d.decisions?.at_stake_aed_per_week), hint: 'Cost of waiting' },
    ],
    actions: [
      {
        title: 'Read the executive brief',
        detail: 'Start with Sage narrative, then open only the decision that needs leadership.',
        href: '/briefing',
        icon: <Sparkles className="h-4 w-4" />,
        priority: 'Now',
      },
      {
        title: 'Approve or delegate top calls',
        detail: 'Review the chain-level decision queue with evidence and expected outcome attached.',
        href: '/decisions',
        icon: <Scale className="h-4 w-4" />,
        priority: 'Now',
      },
      {
        title: 'Check value recovery',
        detail: 'See dead stock, stockout loss, and measured recovery in AED.',
        href: '/value',
        icon: <Briefcase className="h-4 w-4" />,
        priority: 'Next',
      },
    ],
    checks: ['Lead with AED value, keep units separate', 'Show routed work, not every task', 'Surface growth and risk before charts'],
    deepLinks: [
      { label: 'Business health', href: '/value', icon: <Briefcase className="h-4 w-4" /> },
      { label: 'Growth', href: '/analytics', icon: <BarChart3 className="h-4 w-4" /> },
      { label: 'Sage Copilot', href: '/copilot', icon: <Sparkles className="h-4 w-4" /> },
    ],
  },
  {
    key: 'store_manager',
    label: 'Store Manager',
    subtitle: 'One store, shift-ready',
    mission: 'Open ready, fix stockouts fast, confirm reorders, and close the day with fewer unresolved shelf problems.',
    auditVerdict: 'The store manager has useful modules, but the frontend needs a tighter phone-first open/operate/close loop.',
    scope: 'Assigned store',
    primaryQuestion: 'What must I fix on my floor today?',
    owner: 'Store operations',
    currentGap: 'Inventory, alerts, and decisions are separate pages, so the manager has to assemble the morning workflow manually.',
    newFeature: 'Store execution lane with today sales, stockout pressure, low-stock count, and one-tap paths to stock, alerts, and replenishment.',
    badge: 'teal',
    metrics: [
      { label: 'Sold today', value: (d) => count(d.kpis?.total_sales_today, ' units'), hint: 'Today volume' },
      { label: 'Revenue today', value: (d) => AED(d.kpis?.total_revenue_today), hint: 'Today value' },
      { label: 'Out of stock', value: (d) => count(d.inventory?.out_of_stock_count), hint: 'Shelf gaps now' },
      { label: 'Running low', value: (d) => count(d.inventory?.low_stock_count), hint: 'Preventable gaps' },
    ],
    actions: [
      {
        title: 'Clear shelf blockers',
        detail: 'Open inventory with the stockout and low-cover items already top of mind.',
        href: '/inventory',
        icon: <PackageSearch className="h-4 w-4" />,
        priority: 'Now',
      },
      {
        title: 'Confirm replenishment',
        detail: 'Turn low-stock recommendations into purchase or transfer actions.',
        href: '/procurement',
        icon: <Truck className="h-4 w-4" />,
        priority: 'Next',
      },
      {
        title: 'Review active alerts',
        detail: 'Acknowledge the alerts that affect today’s floor execution.',
        href: '/alerts',
        icon: <AlertTriangle className="h-4 w-4" />,
        priority: 'Watch',
      },
    ],
    checks: ['Phone-first and readable while walking', 'Focus on today, not long strategy', 'Use units for stock and AED only for value'],
    deepLinks: [
      { label: 'My work', href: '/decisions', icon: <Scale className="h-4 w-4" /> },
      { label: 'My store', href: '/inventory', icon: <Store className="h-4 w-4" /> },
      { label: 'Briefing', href: '/briefing', icon: <Sparkles className="h-4 w-4" /> },
    ],
  },
  {
    key: 'storekeeper',
    label: 'Storekeeper',
    subtitle: 'Receive, count, shelf',
    mission: 'Keep physical stock trustworthy: receive inbound items, count exceptions, replenish shelves, and flag discrepancies quickly.',
    auditVerdict: 'Storekeeping is present indirectly through inventory screens, but it needs a task-oriented surface for receiving and shelf execution.',
    scope: 'Stockroom and floor inventory',
    primaryQuestion: 'What stock work must be confirmed before it hurts sales?',
    owner: 'Store stockroom',
    currentGap: 'The current frontend is manager-heavy; storekeepers need short operational tasks rather than analytics-heavy views.',
    newFeature: 'Storekeeper lane with receiving, shelf-count, transfer, and discrepancy workflows linked to inventory and procurement.',
    badge: 'amber',
    metrics: [
      { label: 'Out of stock', value: (d) => count(d.inventory?.out_of_stock_count), hint: 'Immediate shelf work' },
      { label: 'Low stock', value: (d) => count(d.inventory?.low_stock_count), hint: 'Replenish before gap' },
      { label: 'Overstocked', value: (d) => count(d.inventory?.overstocked_count), hint: 'Backroom pressure' },
      { label: 'PO approvals', value: (d) => count(d.approvals?.count), hint: 'Inbound work signal' },
    ],
    actions: [
      {
        title: 'Receive inbound stock',
        detail: 'Use purchase-order context, then confirm quantities and flag mismatch.',
        href: '/procurement',
        icon: <PackageCheck className="h-4 w-4" />,
        priority: 'Now',
      },
      {
        title: 'Replenish low-cover shelves',
        detail: 'Work the low-stock list and protect today’s top sellers first.',
        href: '/inventory',
        icon: <Boxes className="h-4 w-4" />,
        priority: 'Now',
      },
      {
        title: 'Escalate discrepancies',
        detail: 'Send count or receiving issues to the manager with evidence.',
        href: '/alerts',
        icon: <ClipboardCheck className="h-4 w-4" />,
        priority: 'Next',
      },
    ],
    checks: ['Scanner/tablet-friendly density', 'No financial clutter except where needed', 'Every task should end in confirm, flag, or escalate'],
    deepLinks: [
      { label: 'Stock list', href: '/inventory', icon: <PackageSearch className="h-4 w-4" /> },
      { label: 'Inbound', href: '/procurement', icon: <Truck className="h-4 w-4" /> },
      { label: 'Alerts', href: '/alerts', icon: <AlertTriangle className="h-4 w-4" /> },
    ],
  },
];

function roleToPersona(role?: UserRole): PersonaKey {
  if (role === 'store_manager') return 'store_manager';
  if (role === 'warehouse_supervisor' || role === 'inventory_support' || role === 'inventory_manager') return 'storekeeper';
  return 'senior_vp';
}

export default function RoleWorkbenchPage() {
  const { user } = useAuth();
  const [activeRole, setActiveRole] = useState<PersonaKey>(() => roleToPersona(user?.role));
  const [doneChecks, setDoneChecks] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setActiveRole(roleToPersona(user?.role));
  }, [user?.role]);

  // Four independent reads, each tolerant of failure (the panel for a missing
  // source just shows em-dashes); only a total wipeout surfaces a page error.
  const kpisQuery = useQuery<Kpis>({ queryKey: ['role-workbench', 'kpis'], queryFn: () => apiGet<Kpis>('/api/kpis') });
  const decisionsQuery = useQuery<DecisionsSummary>({ queryKey: ['role-workbench', 'decisions-summary'], queryFn: () => apiGet<DecisionsSummary>('/api/decisions/summary') });
  const inventoryQuery = useQuery<InventorySummary>({ queryKey: ['role-workbench', 'inventory-summary'], queryFn: () => apiGet<InventorySummary>('/api/inventory/summary') });
  const approvalsQuery = useQuery<ApprovalsSummary>({ queryKey: ['role-workbench', 'approvals'], queryFn: () => apiGet<ApprovalsSummary>('/api/procurement/approvals') });

  const data: WorkbenchData = {
    kpis: kpisQuery.data ?? null,
    decisions: decisionsQuery.data ?? null,
    inventory: inventoryQuery.data ?? null,
    approvals: approvalsQuery.data ?? null,
  };
  // Gate on the combined loading flag so the animated content mounts once (after
  // all four settle) rather than re-rendering per-query mid-entrance.
  const loading = kpisQuery.isLoading || decisionsQuery.isLoading || inventoryQuery.isLoading || approvalsQuery.isLoading;
  const allFailed = kpisQuery.isError && decisionsQuery.isError && inventoryQuery.isError && approvalsQuery.isError;
  const error = allFailed ? 'Could not load role workbench data.' : null;

  const load = () => {
    kpisQuery.refetch();
    decisionsQuery.refetch();
    inventoryQuery.refetch();
    approvalsQuery.refetch();
  };

  const role = useMemo(() => ROLE_SPECS.find((r) => r.key === activeRole) ?? ROLE_SPECS[0], [activeRole]);
  const currentRole = user?.role ? ROLE_DISPLAY_NAMES[user.role] || user.role : 'Demo viewer';

  const toggleCheck = (text: string) => {
    const key = `${role.key}:${text}`;
    setDoneChecks((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <main className="min-h-screen px-4 md:px-8 py-6 md:py-10">
      <div className="mx-auto max-w-6xl space-y-6">
        <section className="hero-mesh relative overflow-hidden rounded-3xl p-6 md:p-8 shadow-elevated">
          <div className="relative z-10 max-w-4xl">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="teal">Frontend audit</Badge>
              <Badge variant="neutral">{currentRole}</Badge>
            </div>
            <h1 className="mt-5 text-2xl md:text-4xl font-semibold leading-tight text-white">
              Role workbench for Senior VP, Store Manager, and Storekeeper
            </h1>
            <p className="mt-3 max-w-3xl text-sm md:text-base leading-relaxed text-white/78">
              The audit finding is simple: the app has strong modules, but these three roles need sharper job-based workflows.
              This page packages the existing data and routes into role-specific operating lanes.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/today">
                <Button variant="secondary">Open my Today <ArrowRight className="h-4 w-4 ms-1" /></Button>
              </Link>
              <Button variant="ghost" onClick={load} className="bg-white/10 text-white hover:bg-white/20 hover:text-white">
                <RefreshCw className={`h-4 w-4 me-1.5 ${loading ? 'animate-spin' : ''}`} /> Refresh data
              </Button>
            </div>
          </div>
        </section>

        <div className="overflow-x-auto pb-1">
          <Tabs
            id="role-workbench-tabs"
            value={activeRole}
            onChange={(id) => setActiveRole(id as PersonaKey)}
            items={ROLE_SPECS.map((r) => ({ id: r.key, label: r.label }))}
          />
        </div>

        {loading ? (
          <div className="grid gap-4 md:grid-cols-2">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : error ? (
          <ErrorState title="Workbench data unavailable" description={error} onRetry={load} />
        ) : (
          <Stagger className="space-y-6">
            <RevealItem>
              <RoleAudit role={role} />
            </RevealItem>

            <RevealItem>
              <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {role.metrics.map((metric) => (
                  <Card key={metric.label} variant="solid" padding="sm">
                    <p className="text-[11px] uppercase tracking-widest text-ink-muted">{metric.label}</p>
                    <p className="mt-1 text-2xl font-bold tabular-nums text-ink">{metric.value(data)}</p>
                    <p className="mt-1 text-xs text-ink-muted">{metric.hint}</p>
                  </Card>
                ))}
              </section>
            </RevealItem>

            <RevealItem>
              <div className="grid gap-6 lg:grid-cols-[1.3fr_0.7fr]">
                <section className="space-y-3">
                  <SectionTitle icon={<Clock3 className="h-4 w-4" />} title={`${role.label} work queue`} />
                  {role.actions.map((action) => (
                    <Link
                      key={action.title}
                      href={action.href}
                      className="group block rounded-lg border border-line bg-surface p-4 shadow-card transition-colors hover:bg-surface-2"
                    >
                      <div className="flex items-start gap-3">
                        <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-teal-700 ring-1 ring-teal-100">
                          {action.icon}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-semibold text-ink">{action.title}</h3>
                            <Badge variant={action.priority === 'Now' ? 'danger' : action.priority === 'Next' ? 'teal' : 'neutral'} size="sm">
                              {action.priority}
                            </Badge>
                          </div>
                          <p className="mt-1 text-sm leading-relaxed text-ink-soft">{action.detail}</p>
                        </div>
                        <ArrowRight className="h-4 w-4 shrink-0 text-ink-muted transition-transform group-hover:translate-x-0.5 group-hover:text-teal-700" />
                      </div>
                    </Link>
                  ))}
                </section>

                <aside className="space-y-4">
                  <Card variant="solid" padding="md">
                    <SectionTitle icon={<ShieldCheck className="h-4 w-4" />} title="UX checks" compact />
                    <div className="mt-3 space-y-2">
                      {role.checks.map((check) => {
                        const checked = doneChecks[`${role.key}:${check}`] ?? false;
                        return (
                          <button
                            key={check}
                            type="button"
                            onClick={() => toggleCheck(check)}
                            className="flex w-full items-start gap-2 rounded-lg px-2 py-2 text-start transition-colors hover:bg-surface-2"
                          >
                            <CheckCircle2 className={`mt-0.5 h-4 w-4 shrink-0 ${checked ? 'text-emerald-600' : 'text-ink-muted'}`} />
                            <span className={`text-sm ${checked ? 'text-ink' : 'text-ink-soft'}`}>{check}</span>
                          </button>
                        );
                      })}
                    </div>
                  </Card>

                  <Card variant="solid" padding="md">
                    <SectionTitle icon={<ArrowRight className="h-4 w-4" />} title="Role shortcuts" compact />
                    <div className="mt-3 grid gap-2">
                      {role.deepLinks.map((link) => (
                        <Link
                          key={link.href + link.label}
                          href={link.href}
                          className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2 text-sm font-medium text-ink-soft transition-colors hover:border-teal-200 hover:bg-teal-50/50 hover:text-teal-800"
                        >
                          <span className="flex items-center gap-2">{link.icon}{link.label}</span>
                          <ArrowRight className="h-3.5 w-3.5" />
                        </Link>
                      ))}
                    </div>
                  </Card>
                </aside>
              </div>
            </RevealItem>
          </Stagger>
        )}
      </div>
    </main>
  );
}

function RoleAudit({ role }: { role: RoleSpec }) {
  return (
    <section className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
      <Card variant="solid" padding="md">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-teal-50 text-teal-700 ring-1 ring-teal-100">
            <ClipboardCheck className="h-5 w-5" />
          </span>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold text-ink">{role.label}</h2>
              <Badge variant={role.badge}>{role.scope}</Badge>
            </div>
            <p className="mt-1 text-sm font-medium text-teal-700">{role.subtitle}</p>
            <p className="mt-3 text-sm leading-relaxed text-ink-soft">{role.mission}</p>
          </div>
        </div>
      </Card>

      <Card variant="solid" padding="md">
        <p className="text-[11px] uppercase tracking-widest text-ink-muted">Audit verdict</p>
        <h3 className="mt-2 text-lg font-semibold text-ink">{role.primaryQuestion}</h3>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">{role.auditVerdict}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <AuditPoint label="Current gap" value={role.currentGap} />
          <AuditPoint label="Feature added" value={role.newFeature} />
        </div>
      </Card>
    </section>
  );
}

function AuditPoint({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-surface-2 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-ink-muted">{label}</p>
      <p className="mt-1 text-sm leading-relaxed text-ink-soft">{value}</p>
    </div>
  );
}

function SectionTitle({ icon, title, compact = false }: { icon: ReactNode; title: string; compact?: boolean }) {
  return (
    <div className={`flex items-center gap-2 ${compact ? '' : 'mb-3'}`}>
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-teal-50 text-teal-700 ring-1 ring-teal-100">
        {icon}
      </span>
      <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink-muted">{title}</h2>
    </div>
  );
}
