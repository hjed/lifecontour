'use client';

/**
 * Strava OAuth callback page.
 *
 * Handles the redirect from Strava after the user authorizes the app.
 * Exchanges the authorization code for tokens via the backend endpoint,
 * then redirects to the integrations page.
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

function StravaCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
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
        const code = searchParams.get('code');
        const state = searchParams.get('state');
        const callbackError = searchParams.get('error');

        if (callbackError) {
          setError(`Strava authorization was denied: ${callbackError}`);
          return;
        }

        if (!code || !state) {
          setError('Missing authorization code or state from Strava');
          return;
        }

        // Exchange the code via the backend Strava callback endpoint
        const response = await fetch(
          '/api/integrations/strava/oauth/callback',
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ code, state }),
            credentials: 'include',
          }
        );

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.detail ?? 'Failed to connect Strava');
        }

        const data = await response.json();

        // Redirect to integrations or wherever specified
        const redirectTo = data.redirect_url ?? '/integrations';
        router.replace(redirectTo);
      } catch (err) {
        console.error('Strava OAuth callback error:', err);
        setError(
          err instanceof Error ? err.message : 'Failed to connect Strava'
        );
      }
    };

    processCallback();
  }, [searchParams, router]);

  if (error) {
    return (
      <Card className='mx-auto mt-12 w-full max-w-md'>
        <CardHeader>
          <CardTitle>Strava Connection Failed</CardTitle>
          <CardDescription>
            There was a problem connecting your Strava account.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Alert variant='destructive'>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
          <button
            className='text-muted-foreground mt-4 text-sm underline'
            onClick={() => router.push('/integrations')}
          >
            Return to Integrations
          </button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className='mx-auto mt-12 w-full max-w-md'>
      <CardHeader>
        <CardTitle>Connecting Strava…</CardTitle>
        <CardDescription>
          Please wait while we finish setting up your Strava connection.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-3'>
        <Skeleton className='h-4 w-full' />
        <Skeleton className='h-4 w-3/4' />
      </CardContent>
    </Card>
  );
}

export default function StravaCallbackPage() {
  return (
    <Suspense
      fallback={
        <Card className='mx-auto mt-12 w-full max-w-md'>
          <CardContent className='py-8'>
            <Skeleton className='h-4 w-full' />
          </CardContent>
        </Card>
      }
    >
      <StravaCallbackContent />
    </Suspense>
  );
}
