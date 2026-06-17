'use client';

import { Modal } from '@/components/ui';
import { Employee } from './types';
import { EmployeeBioCard } from './EmployeeBioCard';
import { EmployeePerformanceChart } from './EmployeePerformanceChart';

interface EmployeeDetailModalProps {
  employee: Employee | null;
  onClose: () => void;
}

export function EmployeeDetailModal({ employee, onClose }: EmployeeDetailModalProps) {
  return (
    <Modal open={!!employee} onClose={onClose} title="Employee Profile" size="lg">
      {employee && (
        <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
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
