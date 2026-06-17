'use client';

import { Store } from 'lucide-react';
import { Card, Table, TableHead, TableBody, TableRow, Th, Td, Badge, SkeletonText, EmptyState } from '@/components/ui';
import { AdminStore } from './types';
import { formatCurrency, formatNumber, formatRelative } from './format';

interface StoresTableProps {
  stores: AdminStore[];
  loading: boolean;
}

export function StoresTable({ stores, loading }: StoresTableProps) {
  return (
    <Card variant="glass" padding="none">
      <div className="px-5 py-4 border-b border-coral-100">
        <h3 className="text-lg font-semibold text-ink">Stores</h3>
        <p className="text-sm text-ink-muted mt-0.5">Locations and trailing-30-day revenue</p>
      </div>

      {loading ? (
        <div className="p-5"><SkeletonText lines={6} /></div>
      ) : stores.length === 0 ? (
        <EmptyState icon={<Store className="w-6 h-6" />} title="No stores found" description="No store records to show." />
      ) : (
        <Table>
          <TableHead>
            <TableRow>
              <Th>Store</Th>
              <Th>Location</Th>
              <Th className="text-right">Revenue (30d)</Th>
              <Th className="text-right">Items Sold</Th>
              <Th>Last Sale</Th>
              <Th className="text-center">Status</Th>
            </TableRow>
          </TableHead>
          <TableBody>
            {stores.map((s) => (
              <TableRow key={s.id}>
                <Td className="font-medium">{s.name}</Td>
                <Td className="text-ink-soft">{s.location}</Td>
                <Td className="text-right font-semibold">{formatCurrency(s.total_sales_30d)}</Td>
                <Td className="text-right text-ink-soft">{formatNumber(s.items_sold)}</Td>
                <Td className="text-ink-soft">{formatRelative(s.last_sale_date)}</Td>
                <Td className="text-center">
                  <Badge variant={s.status === 'active' ? 'success' : 'neutral'} size="sm">{s.status}</Badge>
                </Td>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
