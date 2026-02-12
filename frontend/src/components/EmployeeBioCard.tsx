'use client';

import React from 'react';
import {
  User, Mail, Phone, Calendar, Building, MapPin,
  Award, TrendingUp, Star, Clock, BadgeCheck
} from 'lucide-react';

interface EmployeePerformance {
  performance_score: number;
  performance_grade: string;
  sales_achieved: number;
  customer_rating: number;
  attendance_percentage: number;
}

interface Employee {
  id: number;
  employee_code: string;
  full_name: string;
  first_name: string;
  last_name: string;
  email: string;
  phone?: string;
  role: string;
  department: string;
  designation?: string;
  store_id?: number;
  store_name?: string;
  status: string;
  date_of_joining: string;
  date_of_resignation?: string;
  tenure_days: number;
  photo_url?: string;
  latest_performance_score?: number;
  latest_performance_grade?: string;
  nationality?: string;
  gender?: string;
}

interface EmployeeBioCardProps {
  employee: Employee;
  performance?: EmployeePerformance;
  compact?: boolean;
  onClick?: () => void;
}

const ROLE_COLORS: Record<string, string> = {
  super_admin: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  regional_manager: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  store_manager: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  inventory_manager: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  sales_executive: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200',
  customer_service: 'bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200',
  cashier: 'bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200',
  analyst: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200',
};

const GRADE_COLORS: Record<string, string> = {
  'A+': 'text-green-500 bg-green-100 dark:bg-green-900',
  'A': 'text-green-400 bg-green-50 dark:bg-green-900/50',
  'B+': 'text-blue-500 bg-blue-100 dark:bg-blue-900',
  'B': 'text-blue-400 bg-blue-50 dark:bg-blue-900/50',
  'C': 'text-yellow-500 bg-yellow-100 dark:bg-yellow-900',
  'D': 'text-orange-500 bg-orange-100 dark:bg-orange-900',
  'F': 'text-red-500 bg-red-100 dark:bg-red-900',
};

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-500',
  inactive: 'bg-gray-500',
  terminated: 'bg-red-500',
  on_leave: 'bg-yellow-500',
};

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-AE', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
}

function formatTenure(days: number): string {
  const years = Math.floor(days / 365);
  const months = Math.floor((days % 365) / 30);
  
  if (years > 0) {
    return `${years}y ${months}m`;
  }
  return `${months} months`;
}

function getInitials(firstName: string, lastName: string): string {
  return `${firstName.charAt(0)}${lastName.charAt(0)}`.toUpperCase();
}

export default function EmployeeBioCard({
  employee,
  performance,
  compact = false,
  onClick
}: EmployeeBioCardProps) {
  const grade = employee.latest_performance_grade || performance?.performance_grade || 'N/A';
  const score = employee.latest_performance_score || performance?.performance_score || 0;

  if (compact) {
    return (
      <div 
        className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 hover:shadow-md transition-shadow cursor-pointer"
        onClick={onClick}
      >
        <div className="flex items-center gap-3">
          {/* Avatar */}
          <div className="relative">
            {employee.photo_url ? (
              <img
                src={employee.photo_url}
                alt={employee.full_name}
                className="w-12 h-12 rounded-full object-cover"
              />
            ) : (
              <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-semibold">
                {getInitials(employee.first_name, employee.last_name)}
              </div>
            )}
            <span className={`absolute bottom-0 right-0 w-3 h-3 rounded-full border-2 border-white dark:border-gray-800 ${STATUS_COLORS[employee.status]}`} />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <h4 className="font-semibold text-gray-800 dark:text-white truncate">
              {employee.full_name}
            </h4>
            <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
              {employee.designation || employee.role}
            </p>
          </div>

          {/* Score Badge */}
          <div className={`px-2 py-1 rounded-full text-xs font-bold ${GRADE_COLORS[grade] || 'bg-gray-100 text-gray-600'}`}>
            {grade}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div 
      className="bg-white dark:bg-gray-800 rounded-xl shadow-lg overflow-hidden hover:shadow-xl transition-shadow"
      onClick={onClick}
    >
      {/* Header with gradient */}
      <div className="bg-gradient-to-r from-blue-600 to-purple-600 px-6 py-4">
        <div className="flex items-start gap-4">
          {/* Avatar */}
          <div className="relative">
            {employee.photo_url ? (
              <img
                src={employee.photo_url}
                alt={employee.full_name}
                className="w-20 h-20 rounded-full object-cover border-4 border-white shadow-lg"
              />
            ) : (
              <div className="w-20 h-20 rounded-full bg-white flex items-center justify-center text-2xl font-bold text-blue-600 border-4 border-white shadow-lg">
                {getInitials(employee.first_name, employee.last_name)}
              </div>
            )}
            <span className={`absolute bottom-1 right-1 w-4 h-4 rounded-full border-2 border-white ${STATUS_COLORS[employee.status]}`} />
          </div>

          {/* Basic Info */}
          <div className="flex-1 text-white">
            <h3 className="text-xl font-bold">{employee.full_name}</h3>
            <p className="text-blue-100">{employee.designation || employee.role}</p>
            <div className="flex items-center gap-2 mt-2">
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_COLORS[employee.role] || 'bg-gray-100 text-gray-800'}`}>
                {employee.role.replace('_', ' ').toUpperCase()}
              </span>
              <span className="text-xs text-blue-200">
                {employee.employee_code}
              </span>
            </div>
          </div>

          {/* Performance Score */}
          <div className="text-center">
            <div className={`w-16 h-16 rounded-full flex items-center justify-center text-xl font-bold ${GRADE_COLORS[grade] || 'bg-white text-gray-600'}`}>
              {grade}
            </div>
            <p className="text-xs text-blue-200 mt-1">{score.toFixed(0)}%</p>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="p-6">
        {/* Contact Info */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
            <Mail className="w-4 h-4 text-gray-400" />
            <span className="truncate">{employee.email}</span>
          </div>
          {employee.phone && (
            <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
              <Phone className="w-4 h-4 text-gray-400" />
              <span>{employee.phone}</span>
            </div>
          )}
          {employee.store_name && (
            <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
              <Building className="w-4 h-4 text-gray-400" />
              <span className="truncate">{employee.store_name}</span>
            </div>
          )}
          <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
            <Calendar className="w-4 h-4 text-gray-400" />
            <span>Joined {formatDate(employee.date_of_joining)}</span>
          </div>
        </div>

        {/* Performance Metrics */}
        {performance && (
          <div className="grid grid-cols-4 gap-4 pt-4 border-t border-gray-200 dark:border-gray-700">
            <div className="text-center">
              <div className="flex items-center justify-center mb-1">
                <TrendingUp className="w-4 h-4 text-blue-500" />
              </div>
              <p className="text-lg font-semibold text-gray-800 dark:text-white">
                {performance.sales_achieved.toLocaleString('en-AE', { style: 'currency', currency: 'AED', maximumFractionDigits: 0 })}
              </p>
              <p className="text-xs text-gray-500">Sales</p>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center mb-1">
                <Star className="w-4 h-4 text-yellow-500" />
              </div>
              <p className="text-lg font-semibold text-gray-800 dark:text-white">
                {performance.customer_rating.toFixed(1)}
              </p>
              <p className="text-xs text-gray-500">Rating</p>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center mb-1">
                <Clock className="w-4 h-4 text-green-500" />
              </div>
              <p className="text-lg font-semibold text-gray-800 dark:text-white">
                {performance.attendance_percentage.toFixed(0)}%
              </p>
              <p className="text-xs text-gray-500">Attendance</p>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center mb-1">
                <Award className="w-4 h-4 text-purple-500" />
              </div>
              <p className="text-lg font-semibold text-gray-800 dark:text-white">
                {formatTenure(employee.tenure_days)}
              </p>
              <p className="text-xs text-gray-500">Tenure</p>
            </div>
          </div>
        )}

        {/* Status Bar */}
        {employee.date_of_resignation && (
          <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg">
            <p className="text-sm text-red-600 dark:text-red-400">
              <BadgeCheck className="w-4 h-4 inline mr-1" />
              Resigned on {formatDate(employee.date_of_resignation)}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
