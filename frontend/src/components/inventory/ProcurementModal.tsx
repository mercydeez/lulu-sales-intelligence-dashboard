import { ShoppingCart } from 'lucide-react';
import { Modal, Input, Button } from '@/components/ui';
import { InventoryItem } from './types';
import { formatCurrency } from './format';

export interface ProcurementModalProps {
  open: boolean;
  item: InventoryItem | null;
  quantity: number;
  onQuantityChange: (quantity: number) => void;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function ProcurementModal({ open, item, quantity, onQuantityChange, onCancel, onConfirm }: ProcurementModalProps) {
  if (!item) return null;

  return (
    <Modal open={open} onClose={onCancel} title="Create Procurement Order">
      <div className="flex items-center gap-2 mb-4 text-coral-500">
        <ShoppingCart className="w-5 h-5" />
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm text-ink-muted mb-1">Item</label>
          <p className="text-ink font-medium">{item.item_name}</p>
          <p className="text-sm text-ink-muted">{item.category} • {item.store_name}</p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-ink-muted mb-1">Current Stock</label>
            <p className={`text-lg font-bold ${item.quantity <= 0 ? 'text-rose-600' : 'text-amber-600'}`}>
              {item.quantity}
            </p>
          </div>
          <div>
            <label className="block text-sm text-ink-muted mb-1">Reorder Level</label>
            <p className="text-lg font-bold text-ink">{item.reorder_level}</p>
          </div>
        </div>

        <Input
          label="Order Quantity"
          type="number"
          value={quantity}
          onChange={(e) => onQuantityChange(parseInt(e.target.value) || 0)}
          min={1}
        />

        <div>
          <label className="block text-sm text-ink-muted mb-1">Estimated Cost</label>
          <p className="text-xl font-bold text-coral-600">{formatCurrency(quantity * item.unit_cost)}</p>
        </div>
      </div>

      <div className="flex gap-3 mt-6">
        <Button variant="secondary" className="flex-1" onClick={onCancel}>Cancel</Button>
        <Button className="flex-1" onClick={onConfirm}>Create Order</Button>
      </div>
    </Modal>
  );
}
