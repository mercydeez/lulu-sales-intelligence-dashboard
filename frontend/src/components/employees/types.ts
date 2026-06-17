export interface Employee {
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

export interface EmployeePerformance {
  performance_score: number;
  performance_grade: string;
  sales_achieved: number;
  customer_rating: number;
  attendance_percentage: number;
}

export interface EmployeeSummary {
  total_employees: number;
  by_status: Record<string, number>;
  by_role: Record<string, number>;
  avg_performance_score: number;
  avg_attendance: number;
  avg_customer_rating: number;
  new_hires_this_month: number;
  resignations_this_month: number;
}

export interface RoleAnalytics {
  role: string;
  employee_count: number;
  avg_performance_score: number;
  avg_sales: number;
  avg_customer_rating: number;
  avg_attendance: number;
  total_transactions: number;
}

// Shape returned by GET /api/employees/employees/performance/chart-data
export interface PerformanceChartData {
  labels: string[];
  datasets: {
    performance_score: number[];
    sales: number[];
    customer_rating: number[];
    attendance: number[];
    transactions: number[];
  };
}

export type EmployeeViewMode = 'grid' | 'list';
export type EmployeeTab = 'overview' | 'employees' | 'analytics';
