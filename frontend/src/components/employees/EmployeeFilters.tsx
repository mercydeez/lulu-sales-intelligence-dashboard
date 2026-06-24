'use client';

import { Search, LayoutGrid, List } from 'lucide-react';
import { Card, Input, Select } from '@/components/ui';
import { ROLE_LABELS } from './format';
import { EmployeeViewMode } from './types';

interface EmployeeFiltersProps {
  search: string;
  onSearchChange: (v: string) => void;
  role: string;
  onRoleChange: (v: string) => void;
  status: string;
  onStatusChange: (v: string) => void;
  viewMode: EmployeeViewMode;
  onViewModeChange: (v: EmployeeViewMode) => void;
}

export function EmployeeFilters({
  search, onSearchChange, role, onRoleChange, status, onStatusChange, viewMode, onViewModeChange,
}: EmployeeFiltersProps) {
  return (
    <Card variant="glass" padding="sm" className="mb-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[200px]">
          <Input
            icon={<Search className="w-4 h-4" />}
            placeholder="Search employees..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="!py-2.5"
          />
        </div>
        <Select value={role} onChange={(e) => onRoleChange(e.target.value)} className="!py-2.5 w-48">
          <option value="">All Roles</option>
          {Object.entries(ROLE_LABELS).map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </Select>
        <Select value={status} onChange={(e) => onStatusChange(e.target.value)} className="!py-2.5 w-40">
          <option value="">All Status</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
          <option value="terminated">Terminated</option>
        </Select>
        <div className="flex gap-1 p-1 rounded-2xl bg-coral-50/60">
          <button
            type="button"
            onClick={() => onViewModeChange('grid')}
            aria-label="Grid view"
            className={`p-2 rounded-xl transition-colors ${viewMode === 'grid' ? 'bg-surface text-coral-600 shadow-soft' : 'text-ink-muted hover:text-ink'}`}
          >
            <LayoutGrid className="w-5 h-5" />
          </button>
          <button
            type="button"
            onClick={() => onViewModeChange('list')}
            aria-label="List view"
            className={`p-2 rounded-xl transition-colors ${viewMode === 'list' ? 'bg-surface text-coral-600 shadow-soft' : 'text-ink-muted hover:text-ink'}`}
          >
            <List className="w-5 h-5" />
          </button>
        </div>
      </div>
    </Card>
  );
}
