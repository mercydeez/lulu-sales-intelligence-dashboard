'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, Percent, DollarSign, Package } from 'lucide-react';
import { Modal, Input, Select, Button } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import { fetchStores } from '@/lib/api';
import { Store } from '@/types';
import { DiscountType } from './types';
import { discountDisplay } from './format';

interface PromotionFormModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const CATEGORIES = [
  'Dairy', 'Fruits', 'Vegetables', 'Meat', 'Beverages',
  'Bakery', 'Frozen Foods', 'Household', 'Personal Care', 'Snacks',
];

const DISCOUNT_TYPES: { value: DiscountType; label: string; icon: typeof Percent }[] = [
  { value: 'percentage', label: 'Percentage', icon: Percent },
  { value: 'fixed', label: 'Fixed Amount', icon: DollarSign },
  { value: 'bogo', label: 'Buy 1 Get 1', icon: Package },
];

const todayStr = () => new Date().toISOString().split('T')[0];
const weekOutStr = () => new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];

export function PromotionFormModal({ open, onClose, onSuccess }: PromotionFormModalProps) {
  const { authFetch, user } = useAuth();
  const [stores, setStores] = useState<Store[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [discountType, setDiscountType] = useState<DiscountType>('percentage');
  const [discountValue, setDiscountValue] = useState(10);
  const [minPurchase, setMinPurchase] = useState(0);
  const [maxDiscount, setMaxDiscount] = useState(0);
  const [startDate, setStartDate] = useState(todayStr());
  const [endDate, setEndDate] = useState(weekOutStr());
  const [storeIds, setStoreIds] = useState<number[]>([]);

  // Only offer stores the user can actually create promotions for (backend enforces too).
  const accessible = useMemo(() => user?.accessible_stores ?? [], [user]);
  const selectableStores = useMemo(
    () => (accessible.length > 0 ? stores.filter((s) => accessible.includes(s.id)) : stores),
    [stores, accessible]
  );

  useEffect(() => {
    if (!open) return;
    // Reset on open.
    setName('');
    setDescription('');
    setCategory('');
    setDiscountType('percentage');
    setDiscountValue(10);
    setMinPurchase(0);
    setMaxDiscount(0);
    setStartDate(todayStr());
    setEndDate(weekOutStr());
    setError(null);
    fetchStores()
      .then((list) => {
        setStores(list);
        const ids = (accessible.length > 0 ? list.filter((s) => accessible.includes(s.id)) : list).map((s) => s.id);
        setStoreIds(ids);
      })
      .catch(() => setStores([]));
  }, [open, accessible]);

  const toggleStore = (id: number) =>
    setStoreIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]));

  const validate = (): string | null => {
    if (!name.trim()) return 'Promotion name is required';
    if (!description.trim()) return 'Description is required';
    if (discountType !== 'bogo' && discountValue <= 0) return 'Discount value must be greater than 0';
    if (discountType === 'percentage' && discountValue > 100) return 'Percentage discount cannot exceed 100%';
    if (new Date(endDate) <= new Date(startDate)) return 'End date must be after start date';
    if (storeIds.length === 0) return 'Select at least one store';
    return null;
  };

  const handleSubmit = async () => {
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await authFetch('/api/promotions/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          description,
          discount_type: discountType,
          discount_value: discountType === 'bogo' ? 50 : discountValue,
          category: category || null,
          start_date: startDate,
          end_date: endDate,
          min_purchase: minPurchase > 0 ? minPurchase : null,
          max_discount: maxDiscount > 0 ? maxDiscount : null,
          store_ids: storeIds,
        }),
      });
      if (res.ok) {
        onSuccess();
        onClose();
      } else if (res.status === 403) {
        setError('You are not authorized to create promotions.');
      } else {
        const body = await res.json().catch(() => ({}));
        setError(body.detail || 'Failed to create promotion');
      }
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Create New Promotion" size="lg">
      <div className="space-y-4 max-h-[65vh] overflow-y-auto pe-1">
        {error && (
          <div className="flex items-center gap-2 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <Input label="Promotion Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Weekend Special – Dairy" />

        <div>
          <label className="block text-sm font-medium text-ink-soft mb-2">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="Describe the promotion offer..."
            className="w-full py-3 px-4 rounded-2xl bg-surface border border-line text-ink placeholder-ink-muted shadow-sm transition-all focus:outline-none focus:ring-4 focus:ring-teal-500/15 focus:border-teal-400"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-ink-soft mb-2">Discount Type</label>
          <div className="grid grid-cols-3 gap-3">
            {DISCOUNT_TYPES.map((type) => {
              const Icon = type.icon;
              const selected = discountType === type.value;
              return (
                <button
                  key={type.value}
                  type="button"
                  onClick={() => setDiscountType(type.value)}
                  className={`p-3 rounded-2xl border-2 flex flex-col items-center gap-1.5 transition-all ${
                    selected ? 'border-teal-400 bg-teal-50' : 'border-line hover:border-teal-300'
                  }`}
                >
                  <Icon className={`w-5 h-5 ${selected ? 'text-teal-700' : 'text-ink-muted'}`} />
                  <span className={`text-xs font-medium ${selected ? 'text-ink' : 'text-ink-muted'}`}>{type.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {discountType !== 'bogo' && (
            <Input
              label={`Value ${discountType === 'percentage' ? '(%)' : '(AED)'}`}
              type="number"
              min={1}
              value={discountValue}
              onChange={(e) => setDiscountValue(parseFloat(e.target.value) || 0)}
            />
          )}
          <Input
            label="Min Purchase (AED)"
            type="number"
            min={0}
            value={minPurchase}
            onChange={(e) => setMinPurchase(parseFloat(e.target.value) || 0)}
          />
          <Input
            label="Max Discount (AED)"
            type="number"
            min={0}
            value={maxDiscount}
            onChange={(e) => setMaxDiscount(parseFloat(e.target.value) || 0)}
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Select label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All Categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Select>
          <Input label="Start Date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <Input label="End Date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="block text-sm font-medium text-ink-soft">
              Stores <span className="text-ink-muted font-normal">({storeIds.length} selected)</span>
            </label>
            <button
              type="button"
              onClick={() =>
                setStoreIds(storeIds.length === selectableStores.length ? [] : selectableStores.map((s) => s.id))
              }
              className="text-sm text-teal-700 hover:text-teal-800"
            >
              {storeIds.length === selectableStores.length ? 'Deselect all' : 'Select all'}
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-40 overflow-y-auto">
            {selectableStores.map((store) => {
              const selected = storeIds.includes(store.id);
              return (
                <label
                  key={store.id}
                  className={`flex items-center gap-2 p-2.5 rounded-xl border cursor-pointer text-sm transition-all ${
                    selected ? 'border-teal-400 bg-teal-50 text-ink' : 'border-line text-ink-muted hover:border-teal-300'
                  }`}
                >
                  <input type="checkbox" checked={selected} onChange={() => toggleStore(store.id)} className="accent-teal-600" />
                  <span className="truncate">{store.name}</span>
                </label>
              );
            })}
          </div>
        </div>

        <div className="rounded-2xl sunset-warm on-sunset p-4 text-white">
          <p className="text-xs text-white/80 mb-0.5">Preview</p>
          <p className="text-2xl font-bold">{discountDisplay({ discount_type: discountType, discount_value: discountValue })}</p>
        </div>
      </div>

      <div className="flex gap-3 pt-5">
        <Button variant="secondary" className="flex-1" onClick={onClose}>Cancel</Button>
        <Button variant="primary" className="flex-1" onClick={handleSubmit} loading={submitting}>
          Create Promotion
        </Button>
      </div>
    </Modal>
  );
}
