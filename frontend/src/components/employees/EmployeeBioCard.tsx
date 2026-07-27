'use client';

import { Mail, Phone, Building, Calendar, TrendingUp, Star, Clock, Award, BadgeCheck } from 'lucide-react';
import { Card, Badge } from '@/components/ui';
import { Employee, EmployeePerformance } from './types';
import {
  roleLabel, gradeVariant, statusDot, formatDate, formatTenure, getInitials, formatCurrency,
} from './format';

interface EmployeeBioCardProps {
  employee: Employee;
  performance?: EmployeePerformance;
  compact?: boolean;
  onClick?: () => void;
}

function Avatar({ employee, size }: { employee: Employee; size: number }) {
  const dim = { width: size, height: size };
  return (
    <div className="relative shrink-0">
      {employee.photo_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={employee.photo_url} alt={employee.full_name} className="rounded-full object-cover" style={dim} />
      ) : (
        <div
          className="rounded-full sunset-gradient flex items-center justify-center text-white font-semibold"
          style={dim}
        >
          {getInitials(employee.first_name, employee.last_name)}
        </div>
      )}
      <span
        className={`absolute bottom-0 end-0 w-3 h-3 rounded-full border-2 border-white ${statusDot[employee.status] ?? 'bg-ink-muted'}`}
      />
    </div>
  );
}

export function EmployeeBioCard({ employee, performance, compact = false, onClick }: EmployeeBioCardProps) {
  const grade = employee.latest_performance_grade || performance?.performance_grade || 'N/A';
  const score = employee.latest_performance_score ?? performance?.performance_score ?? 0;

  if (compact) {
    return (
      <Card variant="glass" padding="sm" hover="lift" className="cursor-pointer" onClick={onClick}>
        <div className="flex items-center gap-3">
          <Avatar employee={employee} size={44} />
          <div className="flex-1 min-w-0">
            <h4 className="font-semibold text-ink truncate">{employee.full_name}</h4>
            <p className="text-xs text-ink-muted truncate">{employee.designation || roleLabel(employee.role)}</p>
          </div>
          <Badge variant={gradeVariant(grade)} size="sm">{grade}</Badge>
        </div>
      </Card>
    );
  }

  return (
    <Card variant="glass" padding="none" className="overflow-hidden">
      <div className="sunset-gradient on-sunset px-6 py-5 text-white">
        <div className="flex items-start gap-4">
          <Avatar employee={employee} size={72} />
          <div className="flex-1 min-w-0">
            <h3 className="text-xl font-bold truncate">{employee.full_name}</h3>
            <p className="text-white/80">{employee.designation || roleLabel(employee.role)}</p>
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-surface/20">{roleLabel(employee.role)}</span>
              <span className="text-xs text-white/70 font-mono">{employee.employee_code}</span>
            </div>
          </div>
          <div className="text-center shrink-0">
            <div className="w-14 h-14 rounded-full bg-surface/20 flex items-center justify-center text-xl font-bold">
              {grade}
            </div>
            <p className="text-xs text-white/80 mt-1">{score.toFixed(0)}%</p>
          </div>
        </div>
      </div>

      <div className="p-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
          <div className="flex items-center gap-2 text-sm text-ink-soft">
            <Mail className="w-4 h-4 text-ink-muted" />
            <span className="truncate">{employee.email}</span>
          </div>
          {employee.phone && (
            <div className="flex items-center gap-2 text-sm text-ink-soft">
              <Phone className="w-4 h-4 text-ink-muted" />
              <span>{employee.phone}</span>
            </div>
          )}
          {employee.store_name && (
            <div className="flex items-center gap-2 text-sm text-ink-soft">
              <Building className="w-4 h-4 text-ink-muted" />
              <span className="truncate">{employee.store_name}</span>
            </div>
          )}
          <div className="flex items-center gap-2 text-sm text-ink-soft">
            <Calendar className="w-4 h-4 text-ink-muted" />
            <span>Joined {formatDate(employee.date_of_joining)}</span>
          </div>
        </div>

        {performance && (
          <div className="grid grid-cols-4 gap-3 pt-4 border-t border-line">
            <Metric icon={<TrendingUp className="w-4 h-4 text-teal-600" />} value={formatCurrency(performance.sales_achieved)} label="Sales" />
            <Metric icon={<Star className="w-4 h-4 text-amber-500" />} value={performance.customer_rating.toFixed(1)} label="Rating" />
            <Metric icon={<Clock className="w-4 h-4 text-teal-500" />} value={`${performance.attendance_percentage.toFixed(0)}%`} label="Attendance" />
            <Metric icon={<Award className="w-4 h-4 text-violet-500" />} value={formatTenure(employee.tenure_days)} label="Tenure" />
          </div>
        )}

        {employee.date_of_resignation && (
          <div className="mt-4 p-3 rounded-2xl bg-rose-50 border border-rose-200 text-sm text-rose-700 flex items-center gap-2">
            <BadgeCheck className="w-4 h-4" />
            Resigned on {formatDate(employee.date_of_resignation)}
          </div>
        )}
      </div>
    </Card>
  );
}

function Metric({ icon, value, label }: { icon: React.ReactNode; value: string; label: string }) {
  return (
    <div className="text-center">
      <div className="flex items-center justify-center mb-1">{icon}</div>
      <p className="text-base font-semibold text-ink">{value}</p>
      <p className="text-xs text-ink-muted">{label}</p>
    </div>
  );
}
