import { UserRole } from '@/types/auth';

export interface AdminUser {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: UserRole | string;
  is_active: boolean;
  created_at: string | null;
  last_login: string | null;
}

export interface AdminStore {
  id: number;
  name: string;
  location: string;
  total_sales_30d: number;
  items_sold: number;
  last_sale_date: string | null;
  status: string;
}

export interface ActivityItem {
  type: string;
  message: string;
  date: string | null;
  timestamp: string | null;
}

export interface AdminDashboard {
  users: { total: number; active: number; admins: number; regional_managers: number; store_managers: number };
  stores: { total: number; active: number };
  today: { total_sales: number; active_stores: number; items_sold: number };
  daily_trend: { date: string; sales: number }[];
}

export type AdminTab = 'overview' | 'users' | 'stores' | 'activity';
