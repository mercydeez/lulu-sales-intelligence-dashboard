import Link from 'next/link';
import { AlertTriangle, Package, Bell, ShoppingCart, LucideIcon } from 'lucide-react';

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
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {tiles.map(({ href, label, value, hint, icon: Icon, text, tile, ring }) => (
        <Link
          key={label}
          href={href}
          className={`glass card-pop rounded-2xl p-4 border border-transparent ${ring} group cursor-pointer`}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className={`text-xs uppercase tracking-wider font-semibold ${text}`}>{label}</p>
              <p className={`text-3xl font-bold mt-1 ${text}`}>{value}</p>
              <p className="text-xs text-ink-muted mt-1">{hint}</p>
            </div>
            <div className={`p-3 rounded-2xl ${tile} group-hover:scale-110 transition-transform`}>
              <Icon className="w-7 h-7" />
            </div>
          </div>
        </Link>
      ))}
    </section>
  );
}
