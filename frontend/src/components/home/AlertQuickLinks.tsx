import Link from 'next/link';
import { AlertTriangle, Package, Bell, ShoppingCart, LucideIcon, ArrowRight } from 'lucide-react';

export interface AlertStats {
  outOfStock: number;
  lowStock: number;
  pendingOrders: number;
  criticalAlerts: number;
}

interface TileConfig {
  href: string;
  label: string;
  value: number;
  hint: string;
  icon: LucideIcon;
  text: string;
  tile: string;
  ring: string;
}

export default function AlertQuickLinks({ stats }: { stats: AlertStats }) {
  const tiles: TileConfig[] = [
    {
      href: '/alerts?severity=critical&status=active', label: 'Critical Alerts', value: stats.criticalAlerts,
      hint: 'Require immediate action', icon: AlertTriangle,
      text: 'text-coral-600', tile: 'bg-coral-100 text-coral-600', ring: 'hover:border-coral-300',
    },
    {
      href: '/inventory?status=out_of_stock', label: 'Out of Stock', value: stats.outOfStock,
      hint: 'Items need restock', icon: Package,
      text: 'text-amber-600', tile: 'bg-amber-100 text-amber-600', ring: 'hover:border-amber-300',
    },
    {
      href: '/inventory?status=low_stock', label: 'Low Stock', value: stats.lowStock,
      hint: 'Below reorder level', icon: Bell,
      text: 'text-teal-600', tile: 'bg-teal-100 text-teal-600', ring: 'hover:border-teal-300',
    },
    {
      href: '/approvals', label: 'Pending Orders', value: stats.pendingOrders,
      hint: 'Awaiting approval', icon: ShoppingCart,
      text: 'text-violet-600', tile: 'bg-violet-100 text-violet-600', ring: 'hover:border-violet-300',
    },
  ];

  return (
    <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map(({ href, label, value, hint, icon: Icon, text, tile, ring }) => (
        <Link
          key={label}
          href={href}
          className={`glass card-pop rounded-2xl p-4 border border-transparent ${ring} group cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/50`}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className={`text-xs uppercase tracking-wider font-semibold ${text}`}>{label}</p>
              <p className={`mt-1 text-3xl font-bold tabular-nums ${text}`}>{value}</p>
              <p className="mt-1 text-xs text-ink-muted">{hint}</p>
              <div className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-ink-soft transition-colors group-hover:text-ink">
                Open queue
                <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </div>
            </div>
            <div className={`shrink-0 p-3 rounded-2xl ${tile} group-hover:scale-110 transition-transform`}>
              <Icon className="w-7 h-7" />
            </div>
          </div>
        </Link>
      ))}
    </section>
  );
}
