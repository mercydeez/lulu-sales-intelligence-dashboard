'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Button, SkeletonCard, ErrorState, Stagger, RevealItem, NoPermissionState } from '@/components/ui';
import { apiGet, authFetch, ApiError } from '@/lib/apiClient';
import { TrendingUp, RefreshCw, Info, UploadCloud, Download, Sparkles, ArrowRight } from 'lucide-react';
import Link from 'next/link';

const AED = (n: number | null | undefined, dp = 0) =>
  n == null ? '—' : `AED ${n.toLocaleString('en-AE', { maximumFractionDigits: dp, minimumFractionDigits: dp })}`;

interface Metric { aed?: number | null; value?: number | null; count?: number; per_day_aed?: number;
  projection_days?: number; label: string; needs?: string | null; is_estimate?: boolean;
  gross_margin_90d_aed?: number | null; }
interface RoiSummary {
  currency: string;
  metrics: Record<string, Metric>;
  context: { revenue_90d_aed: number; below_reorder_count: number; total_skus: number;
    total_stock_units: number; has_cost_data: boolean };
  headline: { label: string; aed: number };
}

/**
 * Sage's read of the numbers — composed deterministically from the summary the
 * API already returned (same pattern as the briefing's narrate()). Picks the
 * single biggest lever and the one next step; silent when there's nothing to say.
 */
function sageRead(roi: RoiSummary): { line: string; href: string; cta: string } | null {
  const m = roi.metrics;
  const dead = m.dead_stock?.aed ?? 0;
  const deadCount = m.dead_stock?.count ?? 0;
  const stockout = m.stockout_loss_estimate?.aed ?? 0;
  const belowReorder = roi.context.below_reorder_count;
  if (!dead && !stockout) return null;
  if (dead >= stockout) {
    return {
      line: `Your biggest lever is dead stock: ${AED(dead)} sitting in ${deadCount} SKU${deadCount === 1 ? '' : 's'} with no sale in 60 days. Mark down or transfer to turn it back into cash.`,
      href: '/insights',
      cta: 'See what to fix',
    };
  }
  return {
    line: `Your biggest lever is availability: an estimated ${AED(stockout)} of sales at risk from stockouts${belowReorder ? ` — ${belowReorder} SKU${belowReorder === 1 ? ' is' : 's are'} already below reorder level` : ''}. Reorder before the shelves empty.`,
    href: '/decisions',
    cta: 'Review reorder decisions',
  };
}

export default function ValuePage() {
  const { user } = useAuth();
  const isAdmin = ['super_admin', 'admin', 'regional_manager', 'store_manager'].includes(user?.role ?? '')
    || !!user?.permissions?.can_manage_inventory;
  const [roi, setRoi] = useState<RoiSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setRoi(await apiGet<RoiSummary>('/api/roi/summary')); }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Failed to load value summary'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { if (isAdmin) load(); else setLoading(false); }, [isAdmin, load]);

  const downloadReport = async (fmt: 'html' | 'csv') => {
    const res = await authFetch(`/api/roi/report?fmt=${fmt}`);
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = fmt === 'html' ? 'inventory-value-summary.html' : 'inventory-value.csv';
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };

  if (!isAdmin) {
    return (
      <main className="min-h-screen p-4 md:p-8"><div className="max-w-3xl mx-auto">
        <Card padding="none">
          <NoPermissionState
            title="Operator access required"
            description="Business-value tracking is limited to operator roles."
          />
        </Card>
      </div></main>
    );
  }

  const m = roi?.metrics;
  const empty = roi && roi.context.total_skus === 0;

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        <PageHeader
          title="Value"
          description="What your data is worth in dirhams — cash to release, losses to recover. Computed from your real inventory and sales."
          icon={<TrendingUp className="w-5 h-5" />}
          actions={
            <div className="flex items-center gap-2">
              {roi && !empty && (
                <>
                  <Button variant="secondary" size="md" onClick={() => downloadReport('html')}>
                    <Download className="w-4 h-4 me-1.5" /> Report
                  </Button>
                  <Button variant="secondary" size="md" onClick={() => downloadReport('csv')}>
                    <Download className="w-4 h-4 me-1.5" /> CSV
                  </Button>
                </>
              )}
              <Button variant="secondary" size="md" onClick={load} aria-label="Refresh">
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </Button>
            </div>
          }
        />

        {loading ? <div className="space-y-4"><SkeletonCard /><SkeletonCard /></div>
        : error ? <ErrorState title="Couldn't load value" description={error} onRetry={load} />
        : empty ? (
          <Card padding="lg" className="text-center">
            <UploadCloud className="w-10 h-10 text-teal-500 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-ink">No inventory data yet</h3>
            <p className="text-sm text-ink-muted mt-1 mb-4">Import your inventory and products to see the AED impact.</p>
            <Link href="/imports"><Button>Import data</Button></Link>
          </Card>
        ) : roi && m && (
          <Stagger className="space-y-6">
            {/* Headline */}
            <RevealItem>
              <Card padding="lg" className="text-center bg-teal-50/40">
                <p className="text-sm text-ink-soft">{roi.headline.label}</p>
                <p className="text-4xl font-bold text-teal-700 mt-1">{AED(roi.headline.aed)}</p>
                <p className="text-xs text-ink-muted mt-2">
                  Dead-stock value you could release + projected stockout loss you could recover.
                </p>
              </Card>
            </RevealItem>

            {/* Sage's read: the one lever + the one next step (derived, never padded) */}
            {(() => {
              const read = sageRead(roi);
              return read ? (
                <RevealItem>
                  <div className="flex items-start gap-3 rounded-2xl bg-teal-50/70 ring-1 ring-teal-100 p-4">
                    <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-teal-100 ring-1 ring-teal-200 shrink-0">
                      <Sparkles className="w-4 h-4 text-teal-700" />
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm text-teal-900 leading-relaxed">
                        <span className="font-semibold">Sage&apos;s read:</span> {read.line}
                      </p>
                      <Link href={read.href}
                        className="mt-1.5 inline-flex items-center gap-1 text-sm font-medium text-teal-700 hover:text-teal-800">
                        {read.cta} <ArrowRight className="w-3.5 h-3.5" />
                      </Link>
                    </div>
                  </div>
                </RevealItem>
              ) : null;
            })()}

            {/* Metric grid */}
            <RevealItem>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <MetricCard label={m.inventory_value_retail.label} value={AED(m.inventory_value_retail.aed)} />
                <MetricCard label={m.cash_tied_at_cost.label} value={AED(m.cash_tied_at_cost.aed)} needs={m.cash_tied_at_cost.needs} />
                <MetricCard label={m.dead_stock.label} value={AED(m.dead_stock.aed)} sub={`${m.dead_stock.count} SKUs`} />
                <MetricCard label={m.stockout_loss_estimate.label}
                  value={AED(m.stockout_loss_estimate.aed)}
                  sub={`${AED(m.stockout_loss_estimate.per_day_aed)}/day · ${m.stockout_loss_estimate.projection_days}-day estimate`} />
                <MetricCard label={m.gmroi.label} value={m.gmroi.value == null ? '—' : `${m.gmroi.value}×`}
                  sub={m.gmroi.gross_margin_90d_aed != null ? `${AED(m.gmroi.gross_margin_90d_aed)} margin / 90d` : undefined}
                  needs={m.gmroi.needs} />
                <MetricCard label={m.days_of_supply_avg.label} value={`${m.days_of_supply_avg.value} days`} />
              </div>
            </RevealItem>

            {/* Context */}
            <RevealItem>
              <Card padding="lg">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                  <Ctx label="Revenue (90d)" value={AED(roi.context.revenue_90d_aed)} />
                  <Ctx label="Below reorder" value={`${roi.context.below_reorder_count} SKUs`} />
                  <Ctx label="Total SKUs" value={String(roi.context.total_skus)} />
                  <Ctx label="Units on hand" value={roi.context.total_stock_units.toLocaleString()} />
                </div>
              </Card>
            </RevealItem>

            {!roi.context.has_cost_data && (
              <RevealItem>
                <div className="flex items-start gap-2 rounded-xl bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
                  <Info className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>Add a unit-cost column when you import inventory to unlock cash-at-cost and GMROI. We never estimate cost.</span>
                </div>
              </RevealItem>
            )}
          </Stagger>
        )}
      </div>
    </main>
  );
}

function MetricCard({ label, value, sub, needs }: { label: string; value: string; sub?: string; needs?: string | null }) {
  return (
    <Card padding="lg">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className="text-2xl font-semibold text-ink mt-1">{value}</p>
      {sub && <p className="text-xs text-ink-muted mt-1">{sub}</p>}
      {needs && <p className="text-xs text-amber-600 mt-1">Needs {needs}</p>}
    </Card>
  );
}

function Ctx({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-ink-muted">{label}</p>
      <p className="text-sm font-medium text-ink mt-0.5">{value}</p>
    </div>
  );
}
