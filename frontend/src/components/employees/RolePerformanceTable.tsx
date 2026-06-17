'use client';

import { Star } from 'lucide-react';
import { Card, Table, TableHead, TableBody, TableRow, Th, Td, Badge, SkeletonText, EmptyState } from '@/components/ui';
import { RoleAnalytics } from './types';
import { roleLabel, formatCurrency } from './format';

interface RolePerformanceTableProps {
  roles: RoleAnalytics[];
  loading: boolean;
  onSelectRole?: (role: string) => void;
}

function scoreClass(score: number): string {
  if (score >= 80) return 'text-emerald-600';
  if (score >= 60) return 'text-amber-600';
  return 'text-rose-600';
}

export function RolePerformanceTable({ roles, loading, onSelectRole }: RolePerformanceTableProps) {
  return (
    <Card variant="glass" padding="none">
      <div className="px-5 py-4 border-b border-coral-100">
        <h3 className="text-lg font-semibold text-ink">Performance by Role</h3>
        <p className="text-sm text-ink-muted mt-0.5">Aggregated metrics per role — click a row to filter</p>
      </div>

      {loading ? (
        <div className="p-5"><SkeletonText lines={5} /></div>
      ) : roles.length === 0 ? (
        <EmptyState title="No role data" description="Performance-by-role analytics are unavailable." />
      ) : (
        <Table>
          <TableHead>
            <TableRow>
              <Th>Role</Th>
              <Th className="text-center">Employees</Th>
              <Th className="text-center">Avg Score</Th>
              <Th className="text-right">Avg Sales</Th>
              <Th className="text-center">Rating</Th>
              <Th className="text-center">Attendance</Th>
            </TableRow>
          </TableHead>
          <TableBody>
            {roles.map((role) => (
              <TableRow key={role.role} className="cursor-pointer" onClick={() => onSelectRole?.(role.role)}>
                <Td className="font-medium">{roleLabel(role.role)}</Td>
                <Td className="text-center">
                  <Badge variant="coral" size="sm">{role.employee_count}</Badge>
                </Td>
                <Td className={`text-center font-semibold ${scoreClass(role.avg_performance_score)}`}>
                  {role.avg_performance_score.toFixed(1)}%
                </Td>
                <Td className="text-right text-ink-soft">{formatCurrency(role.avg_sales)}</Td>
                <Td className="text-center">
                  <span className="inline-flex items-center justify-center gap-1 text-ink-soft">
                    <Star className="w-3.5 h-3.5 text-amber-500 fill-amber-500" />
                    {role.avg_customer_rating.toFixed(1)}
                  </span>
                </Td>
                <Td className="text-center text-ink-soft">{role.avg_attendance.toFixed(1)}%</Td>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
