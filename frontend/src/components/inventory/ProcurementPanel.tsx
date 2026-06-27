import { ShoppingCart, Package, Check, X } from 'lucide-react';
import { Badge, Button, Card, Table, TableHead, TableBody, TableRow, Th, Td, EmptyState } from '@/components/ui';
import { ProcurementItem, priorityBadgeVariant, procurementStatusBadgeVariant } from './types';
import { formatCurrency, formatNumber } from './format';

export interface ProcurementPanelProps {
  procurementList: ProcurementItem[];
  pendingProcurement: number;
  canApproveProcurement: boolean;
  onApprove: (procId: number) => void;
  onReject: (procId: number) => void;
}

export default function ProcurementPanel({
  procurementList,
  pendingProcurement,
  canApproveProcurement,
  onApprove,
  onReject,
}: ProcurementPanelProps) {
  const approvedCount = procurementList.filter(p => p.status === 'approved').length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-ink flex items-center gap-2">
          <ShoppingCart className="w-6 h-6 text-teal-600" />
          Procurement Orders
        </h2>
        <div className="flex items-center gap-2">
          <Badge variant="warning" size="md">{pendingProcurement} Pending</Badge>
          <Badge variant="success" size="md">{approvedCount} Approved</Badge>
        </div>
      </div>

      {procurementList.length === 0 ? (
        <Card variant="glass" padding="lg">
          <EmptyState
            icon={<Package className="w-7 h-7" />}
            title="No Procurement Orders"
            description="All inventory levels are adequate"
          />
        </Card>
      ) : (
        <Card variant="glass" padding="none" className="overflow-hidden">
          <Table>
            <TableHead>
              <TableRow>
                <Th>Priority</Th>
                <Th>Item</Th>
                <Th>Store</Th>
                <Th className="text-end">Current Stock</Th>
                <Th className="text-end">Order Qty</Th>
                <Th className="text-end">Est. Cost</Th>
                <Th className="text-center">Status</Th>
                {canApproveProcurement && <Th className="text-center">Actions</Th>}
              </TableRow>
            </TableHead>
            <TableBody>
              {procurementList.map((proc) => (
                <TableRow key={proc.id}>
                  <Td><Badge variant={priorityBadgeVariant[proc.priority]} size="sm">{proc.priority.toUpperCase()}</Badge></Td>
                  <Td>
                    <p className="font-medium text-ink">{proc.item.item_name}</p>
                    <p className="text-sm text-ink-muted">{proc.item.category}</p>
                  </Td>
                  <Td className="text-ink-soft">{proc.item.store_name}</Td>
                  <Td className="text-end">
                    <span className={proc.item.quantity <= 0 ? 'text-rose-600' : 'text-amber-600'}>
                      {proc.item.quantity}
                    </span>
                  </Td>
                  <Td className="text-end font-medium text-ink">{formatNumber(proc.suggestedQuantity)}</Td>
                  <Td className="text-end text-ink">{formatCurrency(proc.suggestedQuantity * proc.item.unit_cost)}</Td>
                  <Td className="text-center">
                    <Badge variant={procurementStatusBadgeVariant[proc.status]} size="sm">
                      {proc.status.charAt(0).toUpperCase() + proc.status.slice(1)}
                    </Badge>
                  </Td>
                  {canApproveProcurement && (
                    <Td className="text-center">
                      {proc.status === 'pending' && (
                        <div className="flex items-center justify-center gap-2">
                          <Button size="sm" onClick={() => onApprove(proc.id)} aria-label="Approve order">
                            <Check className="w-4 h-4" />
                          </Button>
                          <Button size="sm" variant="danger" onClick={() => onReject(proc.id)} aria-label="Reject order">
                            <X className="w-4 h-4" />
                          </Button>
                        </div>
                      )}
                    </Td>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}
