'use client';

/**
 * Authentication guard component for protecting routes.
 *
 * Redirects unauthenticated users to login page
 * and shows loading states appropriately.
 */

import { useEffect } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuth } from '@/lib/auth/AuthProvider';
import { AuthGuardProps } from '@/types/auth';

export function AuthGuard({
  children,
  requireAuth = true,
  fallback,
}: AuthGuardProps) {
  const { state } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Only redirect if authentication is required and user is not authenticated
    if (requireAuth && !state.isLoading && !state.isAuthenticated) {
      const redirectUrl = `/auth/login?redirect=${encodeURIComponent(pathname)}`;
      router.replace(redirectUrl as never);
    }
  }, [requireAuth, state.isAuthenticated, state.isLoading, router, pathname]);

  // Show loading state while checking authentication
  if (state.isLoading) {
    return fallback || <AuthLoadingFallback />;
  }

  // Show children if authentication requirements are met
  if (!requireAuth || state.isAuthenticated) {
    return <>{children}</>;
  }

  // Show fallback while redirecting
  return fallback || <AuthLoadingFallback />;
}

// Default loading fallback component
function AuthLoadingFallback() {
  return (
    <main className='container mx-auto flex min-h-screen items-center justify-center px-4 py-8'>
      <Card className='w-full max-w-md'>
        <CardHeader className='text-center'>
          <CardTitle className='text-xl'>Loading</CardTitle>
          <CardDescription>Checking your authentication status</CardDescription>
        </CardHeader>

        <CardContent className='space-y-4'>
          <div className='space-y-2'>
            <Skeleton className='h-4 w-full' />
            <Skeleton className='h-4 w-3/4' />
            <Skeleton className='h-4 w-1/2' />
          </div>

          <div className='text-muted-foreground text-center text-sm'>
            <p>Please wait...</p>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

// Higher-order component for protecting pages
export function withAuth<P extends object>(
  Component: React.ComponentType<P>,
  options: { requireAuth?: boolean; fallback?: React.ReactNode } = {}
) {
  const { requireAuth = true, fallback } = options;

  return function AuthenticatedComponent(props: P) {
    return (
      <AuthGuard requireAuth={requireAuth} fallback={fallback}>
        <Component {...props} />
      </AuthGuard>
    );
  };
}
