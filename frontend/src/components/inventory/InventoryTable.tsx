import { Package, Building2 } from 'lucide-react';
import { Card, Badge, Button, Table, TableHead, TableBody, TableRow, Th, Td, EmptyState, Skeleton } from '@/components/ui';
import { InventoryItem, statusBadgeVariant, statusLabels } from './types';
import { formatCurrency, formatNumber } from './format';

export interface InventoryTableProps {
  items: InventoryItem[];
  loading: boolean;
  canManageInventory: boolean;
  onAddToProcurement: (item: InventoryItem) => void;
  emptyTitle?: string;
  emptyDescription?: string;
}

export default function InventoryTable({
  items,
  loading,
  canManageInventory,
  onAddToProcurement,
  emptyTitle = 'No items found',
  emptyDescription = 'Try adjusting your filters or search query.',
}: InventoryTableProps) {
  return (
    <Card variant="glass" padding="none" className="overflow-hidden">
      <div className="p-4 border-b border-line flex items-center justify-between">
        <h2 className="text-lg font-semibold text-ink flex items-center gap-2">
          <Package className="w-5 h-5 text-teal-600" />
          Inventory Items
          <Badge variant="neutral" size="sm">{items.length} items</Badge>
        </h2>
      </div>

      <Table>
        <TableHead>
          <TableRow>
            <Th>Item</Th>
            <Th>Store</Th>
            <Th className="text-end">Qty</Th>
            <Th className="text-end">Reorder Level</Th>
            <Th className="text-center">Status</Th>
            <Th className="text-end">Unit Cost</Th>
            <Th className="text-center">Actions</Th>
          </TableRow>
        </TableHead>
        <TableBody>
          {loading ? (
            [...Array(5)].map((_, i) => (
              <TableRow key={i}>
                <Td colSpan={7}><Skeleton height="1.25rem" /></Td>
              </TableRow>
            ))
          ) : items.length === 0 ? (
            <TableRow>
              <Td colSpan={7}>
                <EmptyState icon={<Package className="w-7 h-7" />} title={emptyTitle} description={emptyDescription} />
              </Td>
            </TableRow>
          ) : (
            items.slice(0, 50).map((item) => (
              <TableRow key={item.id}>
                <Td>
                  <p className="font-medium text-ink">{item.item_name}</p>
                  <p className="text-sm text-ink-muted">{item.category}</p>
                </Td>
                <Td>
                  <div className="flex items-center gap-2">
                    <Building2 className="w-4 h-4 text-ink-muted" />
                    <span className="text-sm text-ink-soft">{item.store_name}</span>
                  </div>
                </Td>
                <Td className="text-end">
                  <span className={
                    item.quantity <= 0 ? 'font-medium text-rose-600' :
                    item.quantity <= item.reorder_level ? 'font-medium text-amber-600' :
                    'font-medium text-ink'
                  }>
                    {formatNumber(item.quantity)}
                  </span>
                </Td>
                <Td className="text-end text-ink-muted">{formatNumber(item.reorder_level)}</Td>
                <Td className="text-center">
                  <Badge variant={statusBadgeVariant[item.status]} size="sm">{statusLabels[item.status]}</Badge>
                </Td>
                <Td className="text-end text-ink">{formatCurrency(item.unit_cost)}</Td>
                <Td className="text-center">
                  {(item.status === 'out_of_stock' || item.status === 'low_stock') && canManageInventory && (
                    <Button size="sm" onClick={() => onAddToProcurement(item)}>Create order</Button>
                  )}
                </Td>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </Card>
  );
}
