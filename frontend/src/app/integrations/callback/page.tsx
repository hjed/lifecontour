'use client';

import { Suspense, useEffect, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2, CheckCircle, XCircle } from 'lucide-react';
import { useGoogleOAuthCallback } from '@/lib/api/integrations';

/**
 * Loading fallback for the OAuth callback page.
 * Shown while search params are being loaded.
 */
function LoadingFallback() {
  return (
    <div className='flex min-h-screen items-center justify-center'>
      <output className='block space-y-4 text-center' aria-busy='true'>
        <Loader2
          className='text-primary mx-auto h-12 w-12 animate-spin'
          aria-hidden='true'
        />
        <h1 className='text-xl font-semibold'>Loading...</h1>
      </output>
    </div>
  );
}

/**
 * Inner component that handles the OAuth callback logic.
 * Separated to work with Suspense boundary for useSearchParams.
 */
function OAuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { mutate, isPending, isSuccess, isError, error } =
    useGoogleOAuthCallback();

  // Track if we've already processed the callback
  const processedRef = useRef(false);

  useEffect(() => {
    // Skip if already processed
    if (processedRef.current) return;

    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const errorParam = searchParams.get('error');

    // Handle OAuth error from Google
    if (errorParam) {
      console.error('OAuth error from Google:', errorParam);
      // Redirect to integrations page with error key (XSS safe)
      router.push('/integrations?error=oauth_cancelled');
      return;
    }

    // Handle missing parameters
    if (!code || !state) {
      console.error('Missing OAuth parameters');
      router.push('/integrations?error=invalid_callback');
      return;
    }

    // Mark as processed to prevent double submission
    processedRef.current = true;

    // Exchange code for tokens
    mutate(
      { code, state },
      {
        onSuccess: () => {
          // Redirect to integrations page on success
          setTimeout(() => {
            router.push('/integrations?connected=true');
          }, 1500);
        },
        onError: () => {
          // Redirect to integrations page with error after a delay
          setTimeout(() => {
            router.push('/integrations');
          }, 3000);
        },
      }
    );
  }, [searchParams, mutate, router]);

  return (
    <div className='flex min-h-screen items-center justify-center'>
      <output
        className='block space-y-4 text-center'
        aria-live='polite'
        aria-busy={isPending}
      >
        {isPending && (
          <>
            <Loader2
              className='text-primary mx-auto h-12 w-12 animate-spin'
              aria-hidden='true'
            />
            <h1 className='text-xl font-semibold'>
              Connecting your Google account...
            </h1>
            <p className='text-muted-foreground'>
              Please wait while we complete the connection.
            </p>
          </>
        )}

        {isSuccess && (
          <>
            <CheckCircle className='mx-auto h-12 w-12 text-green-500' />
            <h1 className='text-xl font-semibold text-green-600'>
              Google account connected!
            </h1>
            <p className='text-muted-foreground'>
              Redirecting you back to integrations...
            </p>
          </>
        )}

        {isError && (
          <>
            <XCircle className='mx-auto h-12 w-12 text-red-500' />
            <h1 className='text-xl font-semibold text-red-600'>
              Connection failed
            </h1>
            <p className='text-muted-foreground'>
              {(error as Error)?.message || 'An error occurred'}
            </p>
            <p className='text-muted-foreground text-sm'>
              Redirecting you back to integrations...
            </p>
          </>
        )}
      </output>
    </div>
  );
}

/**
 * Google OAuth callback page.
 *
 * Handles the OAuth callback from Google by exchanging the authorization
 * code for tokens and storing the connected account.
 *
 * Uses Suspense boundary to properly handle useSearchParams() which
 * requires client-side rendering.
 */
export default function OAuthCallbackPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <OAuthCallbackContent />
    </Suspense>
  );
}
