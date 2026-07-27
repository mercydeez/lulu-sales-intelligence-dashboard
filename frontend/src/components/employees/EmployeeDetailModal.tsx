'use client';

import dynamic from 'next/dynamic';
import { createElement } from 'react';
import { Modal, Skeleton } from '@/components/ui';
import { Employee } from './types';
import { EmployeeBioCard } from './EmployeeBioCard';

// Recharts-backed — split out so the employees route doesn't ship it up front;
// the chart only renders inside this modal once an employee is selected.
const EmployeePerformanceChart = dynamic(
  () => import('./EmployeePerformanceChart').then((m) => m.EmployeePerformanceChart),
  { ssr: false, loading: () => createElement(Skeleton, { className: 'h-64 w-full rounded-2xl' }) },
);

interface EmployeeDetailModalProps {
  employee: Employee | null;
  onClose: () => void;
}

export function EmployeeDetailModal({ employee, onClose }: EmployeeDetailModalProps) {
  return (
    <Modal open={!!employee} onClose={onClose} title="Employee Profile" size="lg">
      {employee && (
        <div className="space-y-4 max-h-[70vh] overflow-y-auto pe-1">
          <EmployeeBioCard employee={employee} />
          <EmployeePerformanceChart
            employeeId={employee.id}
            chartType="line"
            title={`${employee.full_name}'s Performance`}
          />
        </div>
      )}
    </Modal>
  );
}
