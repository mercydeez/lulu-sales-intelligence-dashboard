'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Badge, Button, SkeletonCard, EmptyState, Stagger, RevealItem } from '@/components/ui';
import { track } from '@/lib/telemetry';
import { CalendarDays, MapPin, ArrowLeftRight, PackageX, Upload } from 'lucide-react';

const AED = (n: number) => `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: 0 })}`;

interface CalEvent { key: string; name: string; start: string; end: string; approx: boolean;
  note: string; active?: boolean; days_until?: number; }
interface Emirate { emirate: string; units: number; revenue_aed: number; stores: number; }
interface Transfer { item_name: string; from_store: string; to_store: string; suggested_qty: number; reason: string; }
interface DeadEmirate { emirate: string; dead_value_aed: number; dead_skus: number; }

export default function UaeInsightsPage() {
  const { authFetch } = useAuth();
  const [upcoming, setUpcoming] = useState<CalEvent[]>([]);
  const [emirates, setEmirates] = useState<Emirate[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [dead, setDead] = useState<DeadEmirate[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const get = async (p: string) => { const r = await authFetch(p); return r.ok ? r.json() : {}; };
      const [c, e, t, d] = await Promise.all([
        get('/api/uae-intelligence/calendar'),
        get('/api/uae-intelligence/emirate-performance'),
        get('/api/uae-intelligence/transfer-suggestions'),
        get('/api/uae-intelligence/dead-stock-by-emirate'),
      ]);
      setUpcoming(c.upcoming ?? []); setEmirates(e.emirates ?? []);
      setTransfers(t.suggestions ?? []); setDead(d.emirates ?? []);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [authFetch]);
  useEffect(() => { load(); }, [load]);

  const maxRev = Math.max(1, ...emirates.map((e) => e.revenue_aed));

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-5xl mx-auto">
        <PageHeader
          title="UAE insights"
          description="Seasonality, emirate performance and stock moves tuned to the UAE retail calendar."
          icon={<MapPin className="w-5 h-5" />}
        />

        {loading ? <div className="space-y-4"><SkeletonCard /><SkeletonCard /></div> : (
          <Stagger className="space-y-6">
            {/* Calendar */}
            <RevealItem><Card padding="lg">
              <div className="flex items-center gap-2 mb-3"><CalendarDays className="w-4 h-4 text-teal-600" />
                <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">UAE retail calendar — next 60 days</h3></div>
              {upcoming.length === 0 ? <p className="text-sm text-ink-muted">No major UAE retail events in the next 60 days.</p> : (
                <div className="space-y-2">
                  {upcoming.map((e) => (
                    <div key={e.key} className="flex items-start gap-3 rounded-xl border border-line p-3">
                      <Badge variant={e.active ? 'success' : 'amber'}>{e.active ? 'Now' : `in ${e.days_until}d`}</Badge>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-ink">{e.name}{e.approx && <span className="text-xs text-ink-muted"> (approx. dates)</span>}</p>
                        <p className="text-xs text-ink-muted">{e.note}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card></RevealItem>

            {/* Emirate performance */}
            <RevealItem><Card padding="lg">
              <div className="flex items-center gap-2 mb-3"><MapPin className="w-4 h-4 text-teal-600" />
                <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Emirate performance (90d)</h3></div>
              {emirates.length === 0 ? (
                <EmptyState
                  title="No regional data"
                  description="Assign stores to emirates or import sales to see this."
                  action={
                    <Link href="/imports" onClick={() => track('import_cta_clicked', { source: 'uae_insights_empty' })}>
                      <Button variant="secondary" size="sm"><Upload className="w-4 h-4" />Import sales data</Button>
                    </Link>
                  }
                />
              ) : (
                <div className="space-y-3">
                  {emirates.map((e) => (
                    <div key={e.emirate}>
                      <div className="flex items-center justify-between text-sm mb-1">
                        <span className="text-ink">{e.emirate} <span className="text-ink-muted text-xs">· {e.stores} stores</span></span>
                        <span className="text-ink-soft">{AED(e.revenue_aed)}</span>
                      </div>
                      <div className="h-2.5 rounded-full bg-ink/5 overflow-hidden">
                        <div className="h-full rounded-full bg-teal-500" style={{ width: `${(e.revenue_aed / maxRev) * 100}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card></RevealItem>

            {/* Transfer suggestions */}
            <RevealItem><Card padding="lg">
              <div className="flex items-center gap-2 mb-3"><ArrowLeftRight className="w-4 h-4 text-teal-600" />
                <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Branch transfer suggestions</h3></div>
              {transfers.length === 0 ? <p className="text-sm text-ink-muted">No transfers suggested — no overstock/stockout mismatch found.</p> : (
                <div className="space-y-2">
                  {transfers.map((t, i) => (
                    <div key={i} className="rounded-xl border border-line p-3">
                      <p className="text-sm text-ink">
                        Move <span className="font-medium">{t.suggested_qty} × {t.item_name}</span> from{' '}
                        <span className="font-medium">{t.from_store}</span> → <span className="font-medium">{t.to_store}</span>
                      </p>
                      <p className="text-xs text-ink-muted">{t.reason}</p>
                    </div>
                  ))}
                </div>
              )}
              <p className="text-xs text-ink-muted mt-3">Suggestions only — review and approve before moving stock.</p>
            </Card></RevealItem>

            {/* Dead stock by emirate */}
            {dead.length > 0 && (
              <RevealItem><Card padding="lg">
                <div className="flex items-center gap-2 mb-3"><PackageX className="w-4 h-4 text-teal-600" />
                  <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Dead stock by emirate</h3></div>
                <div className="space-y-2">
                  {dead.map((d) => (
                    <div key={d.emirate} className="flex items-center justify-between text-sm">
                      <span className="text-ink">{d.emirate} <span className="text-ink-muted text-xs">· {d.dead_skus} SKUs</span></span>
                      <span className="font-medium text-ink">{AED(d.dead_value_aed)}</span>
                    </div>
                  ))}
                </div>
              </Card></RevealItem>
            )}
          </Stagger>
        )}
      </div>
    </main>
  );
}
