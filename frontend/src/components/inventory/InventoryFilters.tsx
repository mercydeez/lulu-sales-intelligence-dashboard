import { Search, RefreshCw } from 'lucide-react';
import { Card, Input, Select, Button } from '@/components/ui';
import { CategoryData } from './types';

export interface InventoryFiltersProps {
  searchQuery: string;
  onSearchChange: (value: string) => void;
  selectedStore: number | null;
  onStoreChange: (value: number | null) => void;
  selectedCategory: string;
  onCategoryChange: (value: string) => void;
  categories: CategoryData[];
  selectedStatus: string;
  onStatusChange: (value: string) => void;
  onRefresh: () => void;
  loading: boolean;
}

const STORES = [
  { id: 1, name: 'Al Barsha' },
  { id: 2, name: 'Deira City Centre' },
  { id: 3, name: 'Karama' },
  { id: 4, name: 'Mushrif Mall' },
  { id: 5, name: 'Al Wahda' },
];

export default function InventoryFilters({
  searchQuery,
  onSearchChange,
  selectedStore,
  onStoreChange,
  selectedCategory,
  onCategoryChange,
  categories,
  selectedStatus,
  onStatusChange,
  onRefresh,
  loading,
}: InventoryFiltersProps) {
  return (
    <Card variant="glass" padding="md" className="mb-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex-1 min-w-[220px]">
          <Input
            placeholder="Search items, categories, stores..."
            icon={<Search className="w-4 h-4" />}
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        </div>

        <div className="w-44">
          <Select
            value={selectedStore ?? ''}
            onChange={(e) => onStoreChange(e.target.value ? parseInt(e.target.value) : null)}
          >
            <option value="">All Stores</option>
            {STORES.map((store) => (
              <option key={store.id} value={store.id}>{store.name}</option>
            ))}
          </Select>
        </div>

        <div className="w-44">
          <Select
            value={selectedCategory}
            onChange={(e) => onCategoryChange(e.target.value)}
          >
            <option value="">All Categories</option>
            {categories.map((cat) => (
              <option key={cat.category} value={cat.category}>{cat.category}</option>
            ))}
          </Select>
        </div>

        <div className="w-40">
          <Select
            value={selectedStatus}
            onChange={(e) => onStatusChange(e.target.value)}
          >
            <option value="">All Status</option>
            <option value="in_stock">In Stock</option>
            <option value="low_stock">Low Stock</option>
            <option value="out_of_stock">Out of Stock</option>
            <option value="overstocked">Overstocked</option>
          </Select>
        </div>

        <Button variant="secondary" onClick={onRefresh} aria-label="Refresh">
          <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>
    </Card>
  );
}
