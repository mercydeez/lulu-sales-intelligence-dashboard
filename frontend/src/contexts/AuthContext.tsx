'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { User, LoginCredentials, LoginResponse, AuthState, UserRole } from '@/types/auth';
import { authFetch as clientAuthFetch, clearApiCache } from '@/lib/apiClient';
import { Lock } from 'lucide-react';

declare const process: { env: { NEXT_PUBLIC_API_URL?: string } };
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface SignupData {
  company_name: string;
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  seed_sample_data?: boolean;
}

export interface LoginResult {
  ok: boolean;
  requires2fa?: boolean;
  mfaToken?: string;
}

interface AuthContextType extends AuthState {
  login: (credentials: LoginCredentials) => Promise<LoginResult>;
  verifyTwoFactor: (mfaToken: string, code: string) => Promise<boolean>;
  signup: (data: SignupData) => Promise<boolean>;
  logout: () => Promise<void>;
  refreshToken: () => Promise<boolean>;
  hasPermission: (permission: string) => boolean;
  hasRole: (role: UserRole | UserRole[]) => boolean;
  canAccessStore: (storeId: number) => boolean;
  canAccessRegion: (regionCode: string) => boolean;
  clearError: () => void;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextType | null>(null);

// Token storage keys
const ACCESS_TOKEN_KEY = 'app_access_token';
const REFRESH_TOKEN_KEY = 'app_refresh_token';
const USER_KEY = 'app_user';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    error: null
  });

  // Load auth state from storage on mount
  useEffect(() => {
    const loadAuthState = async () => {
      try {
        const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY);
        const storedUser = localStorage.getItem(USER_KEY);

        if (accessToken && storedUser) {
          // Validate token with backend
          const response = await fetch(`${API_URL}/api/auth/validate`, {
            credentials: 'include',
            headers: {
              'Authorization': `Bearer ${accessToken}`
            }
          });

          if (response.ok) {
            const user = JSON.parse(storedUser);
            setState({
              user,
              isAuthenticated: true,
              isLoading: false,
              error: null
            });
          } else {
            // Try to refresh token
            const refreshed = await refreshTokenInternal();
            if (!refreshed) {
              clearAuth();
            }
          }
        } else {
          setState(prev => ({ ...prev, isLoading: false }));
        }
      } catch (error) {
        console.error('Auth load error:', error);
        clearAuth();
      }
    };

    loadAuthState();
  }, []);

  const clearAuth = () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    clearApiCache(); // never let one user's cached data outlive their session (M2)
    setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null
    });
  };

  const signup = async (data: SignupData): Promise<boolean> => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));
    try {
      const response = await fetch(`${API_URL}/api/auth/signup`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seed_sample_data: true, ...data }),
      });
      const body = await response.json();
      if (!response.ok) {
        setState(prev => ({ ...prev, isLoading: false, error: body.detail || 'Sign up failed' }));
        return false;
      }
      const signupResponse: LoginResponse = body;
      clearApiCache();
      localStorage.setItem(ACCESS_TOKEN_KEY, signupResponse.access_token);
      localStorage.setItem(REFRESH_TOKEN_KEY, signupResponse.refresh_token);
      localStorage.setItem(USER_KEY, JSON.stringify(signupResponse.user));
      setState({ user: signupResponse.user, isAuthenticated: true, isLoading: false, error: null });
      return true;
    } catch (error) {
      console.error('Signup error:', error);
      setState(prev => ({ ...prev, isLoading: false, error: 'Network error. Please try again.' }));
      return false;
    }
  };

  // Persist tokens + user from a successful auth response and flip to logged-in.
  const establishSession = (loginResponse: LoginResponse) => {
    clearApiCache(); // drop any cache from a previous session before this user's data lands (M2)
    localStorage.setItem(ACCESS_TOKEN_KEY, loginResponse.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, loginResponse.refresh_token);
    localStorage.setItem(USER_KEY, JSON.stringify(loginResponse.user));
    setState({ user: loginResponse.user, isAuthenticated: true, isLoading: false, error: null });
  };

  const login = async (credentials: LoginCredentials): Promise<LoginResult> => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));

    try {
      const response = await fetch(`${API_URL}/api/auth/login`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(credentials)
      });

      const data = await response.json();

      if (!response.ok) {
        setState(prev => ({ ...prev, isLoading: false, error: data.detail || 'Login failed' }));
        return { ok: false };
      }

      // Account has 2-step verification: not logged in yet — caller collects a code.
      if (data.requires_2fa) {
        setState(prev => ({ ...prev, isLoading: false }));
        return { ok: false, requires2fa: true, mfaToken: data.mfa_token };
      }

      establishSession(data as LoginResponse);
      return { ok: true };
    } catch (error) {
      console.error('Login error:', error);
      setState(prev => ({ ...prev, isLoading: false, error: 'Network error. Please try again.' }));
      return { ok: false };
    }
  };

  const verifyTwoFactor = async (mfaToken: string, code: string): Promise<boolean> => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));
    try {
      const response = await fetch(`${API_URL}/api/auth/2fa/verify`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mfa_token: mfaToken, code }),
      });
      const data = await response.json();
      if (!response.ok) {
        setState(prev => ({ ...prev, isLoading: false, error: data.detail || 'Invalid code' }));
        return false;
      }
      establishSession(data as LoginResponse);
      return true;
    } catch (error) {
      console.error('2FA verify error:', error);
      setState(prev => ({ ...prev, isLoading: false, error: 'Network error. Please try again.' }));
      return false;
    }
  };

  const logout = async (): Promise<void> => {
    try {
      // Always hit the endpoint so the httpOnly cookies get cleared + the token
      // blacklisted, even in a cookie-only session where localStorage is empty.
      const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY);
      await fetch(`${API_URL}/api/auth/logout`, {
        method: 'POST',
        credentials: 'include',
        headers: accessToken ? { 'Authorization': `Bearer ${accessToken}` } : {},
      });
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      clearAuth();
    }
  };

  const refreshTokenInternal = async (): Promise<boolean> => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refreshToken) return false;

    try {
      const response = await fetch(`${API_URL}/api/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ refresh_token: refreshToken })
      });

      if (!response.ok) return false;

      const data: LoginResponse = await response.json();

      localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
      localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));

      setState({
        user: data.user,
        isAuthenticated: true,
        isLoading: false,
        error: null
      });

      return true;
    } catch (error) {
      console.error('Token refresh error:', error);
      return false;
    }
  };

  const refreshToken = useCallback(refreshTokenInternal, []);

  const hasPermission = useCallback((permission: string): boolean => {
    if (!state.user) return false;
    if (state.user.role === 'super_admin') return true;
    return state.user.permissions?.[permission as keyof typeof state.user.permissions] === true;
  }, [state.user]);

  const hasRole = useCallback((role: UserRole | UserRole[]): boolean => {
    if (!state.user) return false;
    const roles = Array.isArray(role) ? role : [role];
    return roles.includes(state.user.role);
  }, [state.user]);

  const canAccessStore = useCallback((storeId: number): boolean => {
    if (!state.user) return false;
    if (state.user.role === 'super_admin') return true;
    return state.user.accessible_stores?.includes(storeId) ?? false;
  }, [state.user]);

  const canAccessRegion = useCallback((regionCode: string): boolean => {
    if (!state.user) return false;
    if (state.user.role === 'super_admin') return true;
    return state.user.accessible_regions?.includes(regionCode) ?? false;
  }, [state.user]);

  const clearError = useCallback(() => {
    setState(prev => ({ ...prev, error: null }));
  }, []);

  // Authenticated fetch — delegates to the single API client (auth + refresh-retry).
  const authFetchInternal = useCallback(
    (url: string, options: RequestInit = {}): Promise<Response> => clientAuthFetch(url, options),
    [],
  );

  return (
    <AuthContext.Provider
      value={{
        ...state,
        login,
        verifyTwoFactor,
        signup,
        logout,
        refreshToken,
        hasPermission,
        hasRole,
        canAccessStore,
        canAccessRegion,
        clearError,
        authFetch: authFetchInternal
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

// HOC for protected routes
export function withAuth<P extends object>(
  Component: React.ComponentType<P>,
  requiredRoles?: UserRole[]
) {
  return function AuthenticatedComponent(props: P) {
    const { isAuthenticated, isLoading, user, hasRole } = useAuth();

    if (isLoading) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-canvas">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-teal-500"></div>
        </div>
      );
    }

    if (!isAuthenticated) {
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
      }
      return null;
    }

    if (requiredRoles && !hasRole(requiredRoles)) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-canvas p-6">
          <div className="text-center max-w-sm rounded-2xl border border-line bg-surface shadow-card p-8">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-coral-50">
              <Lock className="h-6 w-6 text-coral-500" />
            </div>
            <h1 className="text-xl font-bold text-ink mb-1">Access Denied</h1>
            <p className="text-ink-muted text-sm">You don&apos;t have permission to access this page.</p>
          </div>
        </div>
      );
    }

    return <Component {...props} />;
  };
}

// Utility function to get auth header
export function getAuthHeader(): Record<string, string> {
  const token = typeof window !== 'undefined' 
    ? localStorage.getItem(ACCESS_TOKEN_KEY) 
    : null;
  return token ? { 'Authorization': `Bearer ${token}` } : {};
}

// Module-level authenticated fetch for non-React callers — the single API
// client (auth header + 401 refresh-retry + redirect-on-failure).
export const authFetch = clientAuthFetch;
