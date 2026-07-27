'use client';

import { Users } from 'lucide-react';
import { Card, Table, TableHead, TableBody, TableRow, Th, Td, Badge, SkeletonText, EmptyState } from '@/components/ui';
import { Employee, EmployeeViewMode } from './types';
import { EmployeeBioCard } from './EmployeeBioCard';
import { roleLabel, gradeVariant, statusVariant, formatMonthYear, getInitials } from './format';

interface EmployeeListViewProps {
  employees: Employee[];
  loading: boolean;
  viewMode: EmployeeViewMode;
  onSelect: (employee: Employee) => void;
}

export function EmployeeListView({ employees, loading, viewMode, onSelect }: EmployeeListViewProps) {
  if (loading) {
    return (
      <Card variant="glass" padding="md">
        <SkeletonText lines={8} />
      </Card>
    );
  }

  if (employees.length === 0) {
    return (
      <Card variant="glass" padding="lg">
        <EmptyState
          icon={<Users className="w-6 h-6" />}
          title="No employees found"
          description="Try adjusting the filters, or add a new employee."
        />
      </Card>
    );
  }

  if (viewMode === 'grid') {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {employees.map((employee) => (
          <EmployeeBioCard key={employee.id} employee={employee} compact onClick={() => onSelect(employee)} />
        ))}
      </div>
    );
  }

  return (
    <Table>
      <TableHead>
        <TableRow>
          <Th>Employee</Th>
          <Th>Role</Th>
          <Th>Store</Th>
          <Th>Joined</Th>
          <Th className="text-center">Grade</Th>
          <Th className="text-center">Status</Th>
        </TableRow>
      </TableHead>
      <TableBody>
        {employees.map((employee) => (
          <TableRow key={employee.id} className="cursor-pointer" onClick={() => onSelect(employee)}>
            <Td>
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full sunset-gradient flex items-center justify-center text-white text-xs font-semibold shrink-0">
                  {getInitials(employee.first_name, employee.last_name)}
                </div>
                <div className="min-w-0">
                  <p className="font-medium text-ink truncate">{employee.full_name}</p>
                  <p className="text-xs text-ink-muted font-mono">{employee.employee_code}</p>
                </div>
              </div>
            </Td>
            <Td className="text-ink-soft">{roleLabel(employee.role)}</Td>
            <Td className="text-ink-soft">{employee.store_name || 'HQ'}</Td>
            <Td className="text-ink-soft">{formatMonthYear(employee.date_of_joining)}</Td>
            <Td className="text-center">
              <Badge variant={gradeVariant(employee.latest_performance_grade)} size="sm">
                {employee.latest_performance_grade || 'N/A'}
              </Badge>
            </Td>
            <Td className="text-center">
              <Badge variant={statusVariant(employee.status)} size="sm">{employee.status}</Badge>
            </Td>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
