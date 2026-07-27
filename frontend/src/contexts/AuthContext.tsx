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

// Only the user PROFILE is persisted (for cache scoping, E0-6). Access/refresh
// tokens are httpOnly cookies the browser manages — never in localStorage (E0-5).
// The two legacy token keys remain only so clearAuth can purge them from browsers
// that stored them before E0-5.
const LEGACY_ACCESS_TOKEN_KEY = 'app_access_token';
const LEGACY_REFRESH_TOKEN_KEY = 'app_refresh_token';
const USER_KEY = 'app_user';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    error: null
  });

  // Restore the session on mount from the httpOnly cookie (E0-5) — there is no
  // token in localStorage to gate on anymore. Validate with credentials only; on
  // success rehydrate the profile from the stored copy or, if absent, from
  // /api/auth/me (a fresh browser after login-elsewhere, or a cleared profile).
  useEffect(() => {
    const loadAuthState = async () => {
      try {
        let response = await fetch(`${API_URL}/api/auth/validate`, { credentials: 'include' });

        // Access cookie expired but the refresh cookie may still be valid.
        if (!response.ok) {
          const refreshed = await refreshTokenInternal();
          if (!refreshed) { clearAuth(); return; }
          response = await fetch(`${API_URL}/api/auth/validate`, { credentials: 'include' });
          if (!response.ok) { clearAuth(); return; }
        }

        const stored = localStorage.getItem(USER_KEY);
        let user = stored ? JSON.parse(stored) : null;
        if (!user) {
          const me = await fetch(`${API_URL}/api/auth/me`, { credentials: 'include' });
          if (me.ok) {
            user = await me.json();
            localStorage.setItem(USER_KEY, JSON.stringify(user));
          }
        }

        if (user) {
          setState({ user, isAuthenticated: true, isLoading: false, error: null });
        } else {
          clearAuth();
        }
      } catch (error) {
        console.error('Auth load error:', error);
        clearAuth();
      }
    };

    loadAuthState();
  }, []);

  const clearAuth = () => {
    localStorage.removeItem(LEGACY_ACCESS_TOKEN_KEY);
    localStorage.removeItem(LEGACY_REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    clearApiCache(); // never let one user's cached data outlive their session (M2)
    // Drop any open SSE connection now rather than letting it sit out its linger
    // window (hooks/useEventStream.ts). Sent as an event, not a direct call, to
    // avoid an import cycle — that module imports authFetch from this one.
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('auth:logout'));
    }
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
      // Tokens are set as httpOnly cookies by the backend — persist only the
      // profile (used for cache scoping, E0-6), never the tokens (E0-5).
      localStorage.setItem(USER_KEY, JSON.stringify(signupResponse.user));
      setState({ user: signupResponse.user, isAuthenticated: true, isLoading: false, error: null });
      return true;
    } catch (error) {
      console.error('Signup error:', error);
      setState(prev => ({ ...prev, isLoading: false, error: 'Network error. Please try again.' }));
      return false;
    }
  };

  // Flip to logged-in from a successful auth response. Tokens arrived as httpOnly
  // cookies (Set-Cookie); we persist ONLY the profile for cache scoping (E0-5/E0-6).
  const establishSession = (loginResponse: LoginResponse) => {
    clearApiCache(); // drop any cache from a previous session before this user's data lands (M2)
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
      // Route through authFetch so the httpOnly cookies are sent and the CSRF
      // double-submit header is attached — logout is a state-changing POST and
      // is no longer Bearer-exempt. This clears the cookies + blacklists the token.
      await clientAuthFetch(`${API_URL}/api/auth/logout`, { method: 'POST' });
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      clearAuth();
    }
  };

  const refreshTokenInternal = async (): Promise<boolean> => {
    try {
      // The refresh token is an httpOnly cookie — send NO body (the endpoint
      // requires a token field, so `{}` would 422; it falls back to the cookie
      // when the body is absent). Rotated cookies come back as Set-Cookie.
      const response = await fetch(`${API_URL}/api/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) return false;

      const data: LoginResponse = await response.json();

      // Persist ONLY the profile — tokens live in the refreshed httpOnly cookies.
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

// Module-level authenticated fetch for non-React callers — the single API
// client (httpOnly-cookie auth + CSRF header + 401 refresh-retry + redirect).
export const authFetch = clientAuthFetch;
