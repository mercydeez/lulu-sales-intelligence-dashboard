'use client';

import { useEffect, useState } from 'react';
import { Store } from 'lucide-react';
import { Card, Table, TableHead, TableBody, TableRow, Th, Td, Skeleton, EmptyState } from '@/components/ui';
import { fetchStoreDistribution } from '@/lib/api';
import { StoreDistributionPoint } from '@/types';
import { seriesColor } from '@/lib/chart';
import { formatCurrency } from './format';

export function StorePerformanceTable() {
  const [data, setData] = useState<StoreDistributionPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchStoreDistribution()
      .then((res) => {
        if (!cancelled) setData(res.data ?? []);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Card variant="glass" padding="md">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 rounded-xl bg-violet-100 text-violet-600">
          <Store className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-ink">Store Performance</h3>
          <p className="text-sm text-ink-muted">Ranked by total revenue across the period</p>
        </div>
      </div>

      {loading ? (
        <Skeleton width="100%" height="220px" rounded="lg" />
      ) : error || data.length === 0 ? (
        <EmptyState title="No store data" description="Revenue by store is unavailable for your access scope." />
      ) : (
        <Table>
          <TableHead>
            <TableRow>
              <Th>#</Th>
              <Th>Store</Th>
              <Th className="text-end">Revenue</Th>
              <Th className="w-[34%]">Share</Th>
            </TableRow>
          </TableHead>
          <TableBody>
            {(() => {
              // Scale every store's bar relative to the leader so the ranking
              // reads at a glance; the label still shows the true % of total.
              const maxPct = Math.max(1, ...data.map((s) => s.percentage));
              return data.map((store, index) => {
                const color = seriesColor(index);
                return (
                  <TableRow key={store.store_id}>
                    <Td>
                      <span
                        className="inline-flex w-7 h-7 items-center justify-center rounded-lg text-white text-xs font-bold"
                        style={{ background: color }}
                      >
                        {index + 1}
                      </span>
                    </Td>
                    <Td className="font-medium">{store.store_name}</Td>
                    <Td className="text-end font-semibold tabular-nums">{formatCurrency(store.total_revenue)}</Td>
                    <Td>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-2 rounded-full bg-ink/5 overflow-hidden">
                          <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${(store.percentage / maxPct) * 100}%`, background: color }}
                          />
                        </div>
                        <span className="w-12 text-end text-sm text-ink-soft tabular-nums">
                          {store.percentage.toFixed(1)}%
                        </span>
                      </div>
                    </Td>
                  </TableRow>
                );
              });
            })()}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
