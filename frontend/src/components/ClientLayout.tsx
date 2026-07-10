'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, ReactNode } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useExperience } from '@/contexts/ExperienceContext';
import { AppShell } from '@/components/shell';
import { initTelemetry, identify, resetIdentity, track } from '@/lib/telemetry';

// Signed-out account-lifecycle pages (redirect authed users to home, let
// signed-out visitors through). Each is the destination of a link or an email
// that its audience opens while logged out — omitting one bounces that entire
// audience to /login. `/accept-invite` activates a brand-new account from an
// emailed token; `/signup` is linked from login as "Create your workspace".
const publicPaths = [
  '/login', '/signup', '/accept-invite', '/forgot-password', '/reset-password', '/dev',
];

// Truly open pages: reachable signed-in OR out, no redirect in either
// direction, rendered without the shell.
// - /status must stay reachable even when auth (and the API) is down.
// - /verify-email runs an emailed token: clicked post-registration (signed
//   out) or after an email change (signed in) — a redirect either way aborts
//   verification before it runs.
// - /trust is the public data-residency/compliance statement (public API,
//   evaluated by prospects who aren't logged in).
const openPaths = ['/status', '/verify-email', '/trust'];

export default function ClientLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isLoading, user } = useAuth();
  const { config } = useExperience();

  // Telemetry (measurement loop): init after first paint; bind/unbind the
  // session to ids only (no PII — see lib/telemetry.ts); SPA-correct pageviews.
  useEffect(() => {
    initTelemetry();
  }, []);
  useEffect(() => {
    if (isLoading) return;
    if (isAuthenticated && user?.id) identify(user.id, { role: user.role });
    else if (!isAuthenticated) resetIdentity();
  }, [isAuthenticated, isLoading, user?.id, user?.role]);
  useEffect(() => {
    if (pathname) track('page_viewed', { path: pathname });
  }, [pathname]);

  // Match a public path exactly or as a path segment — NOT as a bare prefix, or
  // '/dev' would swallow '/developers' and bounce authed users to the dashboard.
  const isPublicPath = publicPaths.some(
    (path) => pathname === path || pathname?.startsWith(path + '/')
  );
  const isOpenPath = openPaths.some(
    (path) => pathname === path || pathname?.startsWith(path + '/')
  );

  useEffect(() => {
    if (!isLoading && !isOpenPath) {
      if (!isAuthenticated && !isPublicPath) {
        // Redirect to login if not authenticated and not on public page
        router.push('/login');
      } else if (isAuthenticated && isPublicPath) {
        // Redirect to the role's home (Role Experience Engine) — '/' by default
        router.push(config?.home && config.home !== '/' ? config.home : '/');
      }
    }
  }, [isAuthenticated, isLoading, isPublicPath, isOpenPath, pathname, router, config?.home]);

  // Role home: wave-1 roles live on /today; send them there from the generic
  // dashboard root once their config arrives. Other roles keep '/' unchanged.
  useEffect(() => {
    if (!isLoading && isAuthenticated && pathname === '/' && config?.home && config.home !== '/') {
      router.replace(config.home);
    }
  }, [isLoading, isAuthenticated, pathname, config?.home, router]);

  // Open pages render immediately — never gated behind the auth check, so
  // /status stays reachable while the API (and therefore auth) is down.
  if (isOpenPath) {
    return <>{children}</>;
  }

  // Show loading while checking auth
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-teal-500 mx-auto mb-4"></div>
          <p className="text-ink-muted">Loading...</p>
        </div>
      </div>
    );
  }

  // Public pages don't need navbar
  if (isPublicPath) {
    return <>{children}</>;
  }

  // Protected pages get the app shell (sidebar + topbar)
  return <AppShell>{children}</AppShell>;
}
