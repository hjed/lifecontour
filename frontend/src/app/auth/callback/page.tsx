'use client';

/**
 * OAuth callback page to handle authentication redirects.
 *
 * Processes OAuth callback and redirects to appropriate page
 * following the backend session-based authentication flow.
 */

import { useEffect, useState, useRef, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuth } from '@/lib/auth/AuthProvider';

// Component that uses useSearchParams - needs to be wrapped in Suspense
function CallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { refreshSession } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const processedRef = useRef(false);

  useEffect(() => {
    const processCallback = async () => {
      // Prevent multiple callback processing
      if (processedRef.current) {
        return;
      }
      processedRef.current = true;

      try {
        // Get OAuth parameters from URL
        const code = searchParams.get('code');
        const state = searchParams.get('state');
        const error = searchParams.get('error');
        const errorDescription = searchParams.get('error_description');

        // Handle OAuth errors
        if (error) {
          throw new Error(errorDescription ?? `OAuth error: ${error}`);
        }

        // Validate required parameters
        if (!code || !state) {
          throw new Error('Missing required OAuth parameters');
        }

        // Get provider from sessionStorage (stored during login)
        const provider = sessionStorage.getItem('oauth_provider') || 'generic';

        // Send callback data to backend
        const response = await fetch('/api/auth/callback', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            code,
            state,
            provider,
          }),
          credentials: 'include',
        });

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(
            errorData.errors?.[0]?.detail ?? 'Authentication failed'
          );
        }

        const data = await response.json();

        // Refresh session to get user data
        await refreshSession();

        // Clean up stored provider
        sessionStorage.removeItem('oauth_provider');

        // Redirect to intended destination or dashboard
        const redirectTo = data.redirect_url ?? '/';
        router.replace(redirectTo);
      } catch (err) {
        console.error('OAuth callback error:', err);
        setError(err instanceof Error ? err.message : 'Authentication failed');
      }
    };

    processCallback();
  }, [searchParams, router, refreshSession]);

  // Show error state
  if (error) {
    return (
      <main className='container mx-auto flex min-h-screen items-center justify-center px-4 py-8'>
        <Card className='w-full max-w-md'>
          <CardHeader className='text-center'>
            <CardTitle className='text-destructive text-xl'>
              Authentication Failed
            </CardTitle>
            <CardDescription>
              There was a problem signing you in
            </CardDescription>
          </CardHeader>

          <CardContent className='space-y-4'>
            <Alert variant='destructive'>
              <AlertDescription>{error}</AlertDescription>
            </Alert>

            <div className='text-center'>
              <button
                onClick={() => router.push('/auth/login' as never)}
                className='text-muted-foreground hover:text-foreground text-sm underline'
              >
                Try signing in again
              </button>
            </div>
          </CardContent>
        </Card>
      </main>
    );
  }

  // Show loading state
  return (
    <main className='container mx-auto flex min-h-screen items-center justify-center px-4 py-8'>
      <Card className='w-full max-w-md'>
        <CardHeader className='text-center'>
          <CardTitle className='text-xl'>Completing Sign In</CardTitle>
          <CardDescription>
            Please wait while we finish setting up your session
          </CardDescription>
        </CardHeader>

        <CardContent className='space-y-4'>
          <div className='space-y-2'>
            <Skeleton className='h-4 w-full' />
            <Skeleton className='h-4 w-3/4' />
            <Skeleton className='h-4 w-1/2' />
          </div>

          <div className='text-muted-foreground text-center text-sm'>
            <p>This should only take a moment...</p>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

export default function CallbackPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <CallbackContent />
    </Suspense>
  );
}
