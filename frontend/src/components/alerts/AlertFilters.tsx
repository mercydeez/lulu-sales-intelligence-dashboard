import { RefreshCw } from 'lucide-react';
import { Card, Select, Button } from '@/components/ui';

export interface AlertFiltersProps {
  severity: string;
  onSeverityChange: (value: string) => void;
  status: string;
  onStatusChange: (value: string) => void;
  category: string;
  onCategoryChange: (value: string) => void;
  onRefresh: () => void;
  loading: boolean;
}

export default function AlertFilters({
  severity,
  onSeverityChange,
  status,
  onStatusChange,
  category,
  onCategoryChange,
  onRefresh,
  loading,
}: AlertFiltersProps) {
  return (
    <Card variant="glass" padding="md" className="mb-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-44">
          <Select value={severity} onChange={(e) => onSeverityChange(e.target.value)}>
            <option value="">All Severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </Select>
        </div>

        <div className="w-44">
          <Select value={status} onChange={(e) => onStatusChange(e.target.value)}>
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </Select>
        </div>

        <div className="w-44">
          <Select value={category} onChange={(e) => onCategoryChange(e.target.value)}>
            <option value="">All Types</option>
            <option value="inventory">Inventory</option>
            <option value="expiry">Expiry</option>
            <option value="sales">Sales</option>
            <option value="system">System</option>
          </Select>
        </div>

        <Button variant="secondary" onClick={onRefresh} aria-label="Refresh">
          <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>
    </Card>
  );
}
