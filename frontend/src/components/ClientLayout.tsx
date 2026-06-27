'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, ReactNode } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { AppShell } from '@/components/shell';

// Pages that don't require authentication
const publicPaths = ['/login', '/forgot-password', '/reset-password', '/dev'];

export default function ClientLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();
  
  // Match a public path exactly or as a path segment — NOT as a bare prefix, or
  // '/dev' would swallow '/developers' and bounce authed users to the dashboard.
  const isPublicPath = publicPaths.some(
    (path) => pathname === path || pathname?.startsWith(path + '/')
  );

  useEffect(() => {
    if (!isLoading) {
      if (!isAuthenticated && !isPublicPath) {
        // Redirect to login if not authenticated and not on public page
        router.push('/login');
      } else if (isAuthenticated && isPublicPath) {
        // Redirect to dashboard if authenticated and on login page
        router.push('/');
      }
    }
  }, [isAuthenticated, isLoading, isPublicPath, pathname, router]);

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
