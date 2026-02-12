// Authentication Types
export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  full_name?: string;
  role: UserRole;
  role_display?: string;
  status: string;
  job_title?: string;
  department?: string;
  last_login_at?: string;
  permissions: UserPermissions;
  accessible_stores: number[];
  accessible_regions: string[];
}

export type UserRole = 
  | 'super_admin' 
  | 'regional_manager' 
  | 'store_manager' 
  | 'analyst'
  | 'inventory_manager'
  | 'sales_executive'
  | 'cashier'
  | 'security'
  | 'inventory_support'
  | 'sales_intern'
  | 'procurement_officer'
  | 'warehouse_supervisor'
  | 'customer_service';

export interface UserPermissions {
  accessible_stores: number[];
  accessible_regions: string[];
  can_view: boolean;
  can_edit: boolean;
  can_delete: boolean;
  can_export: boolean;
  can_manage_users: boolean;
  can_manage_inventory: boolean;
  can_manage_promotions: boolean;
  can_view_financials: boolean;
  can_approve_transfers: boolean;
  can_use_ai_chat?: boolean;
  can_use_voice_chat?: boolean;
  can_approve_procurement?: boolean;
  can_manage_stock?: boolean;
  can_process_transactions?: boolean;
}

export interface LoginCredentials {
  email: string;
  password: string;
  remember_me?: boolean;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface LoginResponse extends AuthTokens {
  user: User;
}

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
}

// Role hierarchy for permission checking
export const ROLE_HIERARCHY: Record<UserRole, number> = {
  'super_admin': 100,
  'regional_manager': 90,
  'store_manager': 80,
  'inventory_manager': 70,
  'procurement_officer': 65,
  'warehouse_supervisor': 60,
  'sales_executive': 55,
  'analyst': 50,
  'customer_service': 45,
  'inventory_support': 40,
  'cashier': 35,
  'sales_intern': 30,
  'security': 25
};

// Role display names
export const ROLE_DISPLAY_NAMES: Record<UserRole, string> = {
  'super_admin': 'Senior VP',
  'regional_manager': 'Regional Manager',
  'store_manager': 'Store Manager',
  'analyst': 'Business Analyst',
  'inventory_manager': 'Inventory Manager',
  'sales_executive': 'Sales Executive',
  'cashier': 'Cashier',
  'security': 'Security Officer',
  'inventory_support': 'Inventory Support',
  'sales_intern': 'Sales Intern',
  'procurement_officer': 'Procurement Officer',
  'warehouse_supervisor': 'Warehouse Supervisor',
  'customer_service': 'Customer Service Rep'
};

// Role categories for grouping in UI
export const ROLE_CATEGORIES: Record<string, UserRole[]> = {
  'Management': ['super_admin', 'regional_manager', 'store_manager'],
  'Inventory & Procurement': ['inventory_manager', 'procurement_officer', 'warehouse_supervisor', 'inventory_support'],
  'Sales': ['sales_executive', 'cashier', 'sales_intern'],
  'Support': ['analyst', 'customer_service', 'security']
};

// Default permissions by role
export const DEFAULT_ROLE_PERMISSIONS: Record<UserRole, Partial<UserPermissions>> = {
  'super_admin': {
    can_view: true, can_edit: true, can_delete: true, can_export: true,
    can_manage_users: true, can_manage_inventory: true, can_manage_promotions: true,
    can_view_financials: true, can_approve_transfers: true, can_approve_procurement: true,
    can_manage_stock: true, can_process_transactions: true
  },
  'regional_manager': {
    can_view: true, can_edit: true, can_delete: false, can_export: true,
    can_manage_users: false, can_manage_inventory: true, can_manage_promotions: true,
    can_view_financials: true, can_approve_transfers: true, can_approve_procurement: true
  },
  'store_manager': {
    can_view: true, can_edit: true, can_delete: false, can_export: true,
    can_manage_inventory: true, can_manage_promotions: true, can_approve_transfers: true
  },
  'inventory_manager': {
    can_view: true, can_edit: true, can_manage_inventory: true,
    can_approve_transfers: true, can_approve_procurement: true, can_manage_stock: true
  },
  'procurement_officer': {
    can_view: true, can_edit: true, can_manage_inventory: true, can_approve_procurement: true
  },
  'warehouse_supervisor': {
    can_view: true, can_edit: true, can_manage_inventory: true, can_manage_stock: true
  },
  'sales_executive': {
    can_view: true, can_edit: true, can_manage_promotions: true, can_process_transactions: true
  },
  'analyst': {
    can_view: true, can_export: true, can_view_financials: true
  },
  'customer_service': {
    can_view: true, can_edit: false
  },
  'inventory_support': {
    can_view: true, can_manage_stock: true
  },
  'cashier': {
    can_view: true, can_process_transactions: true
  },
  'sales_intern': {
    can_view: true
  },
  'security': {
    can_view: true
  }
};

// Permission labels for UI
export const PERMISSION_LABELS: Record<string, string> = {
  can_view: 'View Data',
  can_edit: 'Edit Records',
  can_delete: 'Delete Records',
  can_export: 'Export Data',
  can_manage_users: 'Manage Users',
  can_manage_inventory: 'Manage Inventory',
  can_manage_promotions: 'Manage Promotions',
  can_view_financials: 'View Financials',
  can_approve_transfers: 'Approve Transfers',
  can_approve_procurement: 'Approve Procurement',
  can_manage_stock: 'Manage Stock Levels',
  can_process_transactions: 'Process Transactions'
};
