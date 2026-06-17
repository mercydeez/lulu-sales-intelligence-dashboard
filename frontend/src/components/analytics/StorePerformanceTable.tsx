'use client';

import { useEffect, useState } from 'react';
import { Store } from 'lucide-react';
import { Card, Table, TableHead, TableBody, TableRow, Th, Td, Skeleton, EmptyState, Badge } from '@/components/ui';
import { fetchStoreDistribution } from '@/lib/api';
import { StoreDistributionPoint } from '@/types';
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
              <Th className="text-right">Revenue</Th>
              <Th className="text-right">Share</Th>
            </TableRow>
          </TableHead>
          <TableBody>
            {data.map((store, index) => (
              <TableRow key={store.store_id}>
                <Td>
                  <span className="inline-flex w-7 h-7 items-center justify-center rounded-lg sunset-gradient text-white text-xs font-bold">
                    {index + 1}
                  </span>
                </Td>
                <Td className="font-medium">{store.store_name}</Td>
                <Td className="text-right font-semibold">{formatCurrency(store.total_sales)}</Td>
                <Td className="text-right">
                  <Badge variant={index === 0 ? 'coral' : 'neutral'} size="sm">{store.percentage.toFixed(1)}%</Badge>
                </Td>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
