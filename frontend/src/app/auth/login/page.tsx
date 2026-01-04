'use client';

/**
 * Login page with OAuth provider options.
 *
 * Implements dedicated login page as per user requirements
 * with Australian English localization and accessibility.
 */

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Separator } from '@/components/ui/separator';
import { useAuth } from '@/lib/auth/AuthProvider';
import { UI_TEXT, API_ENDPOINTS } from '@/lib/constants';
import { GitBranch, Key } from 'lucide-react';

// Provider interface for backend response
interface ProviderInfo {
  name: string;
  display_name: string;
  icon_url?: string;
}

// OAuth provider icons - default to Key for all providers
const getProviderIcon = (providerName: string) => {
  switch (providerName.toLowerCase()) {
    case 'github':
      return GitBranch;
    default:
      return Key;
  }
};

// Component that uses useSearchParams - needs to be wrapped in Suspense
function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { state, login } = useAuth();
  const [loadingProvider, setLoadingProvider] = useState<string | null>(null);

  // Get redirect URL from query params
  const redirectTo = searchParams.get('redirect') || '/';

  // Fetch available providers from backend
  const { data: providersData, isLoading: isLoadingProviders } = useQuery({
    queryKey: ['auth', 'providers'],
    queryFn: async (): Promise<{ providers: ProviderInfo[] }> => {
      const response = await fetch(API_ENDPOINTS.AUTH.PROVIDERS, {
        credentials: 'include',
      });
      if (!response.ok) {
        throw new Error('Failed to fetch providers');
      }
      return response.json();
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Redirect authenticated users away from login page
  useEffect(() => {
    if (state.isAuthenticated && !state.isLoading) {
      router.replace(redirectTo as never);
    }
  }, [state.isAuthenticated, state.isLoading, router, redirectTo]);

  // Handle OAuth login
  const handleLogin = (providerName: string) => {
    setLoadingProvider(providerName);
    login(providerName);
    // Redirect happens in AuthProvider after successful OAuth
    // Error handling is done in AuthProvider's onError callback
    // Loading state will be cleared when mutation completes
  };

  // Don't render login form if authenticated (redirect will happen in useEffect)
  if (state.isAuthenticated) {
    return null;
  }

  return (
    <div className='flex min-h-screen items-center justify-center px-4 py-8'>
      <Card className='w-full max-w-md'>
        <CardHeader className='space-y-1 text-center'>
          <h1 className='text-2xl font-bold tracking-tight'>
            {UI_TEXT.WELCOME_BACK}
          </h1>
          <CardDescription>{UI_TEXT.SIGN_IN_DESCRIPTION}</CardDescription>
        </CardHeader>

        <CardContent className='space-y-4'>
          {/* Error message */}
          {state.error && (
            <Alert variant='destructive'>
              <AlertDescription>{state.error}</AlertDescription>
            </Alert>
          )}

          {/* OAuth provider buttons */}
          <div className='space-y-3'>
            {isLoadingProviders ? (
              <div className='text-muted-foreground text-center'>
                Loading providers...
              </div>
            ) : providersData?.providers?.length ? (
              providersData.providers.map(provider => {
                const Icon = getProviderIcon(provider.name);
                // Show loading if this provider was clicked and auth is still loading
                const isLoading =
                  loadingProvider === provider.name && state.isLoading;
                // Disable all buttons if any provider is loading
                const isAnyLoading =
                  loadingProvider !== null && state.isLoading;

                return (
                  <Button
                    key={provider.name}
                    variant='outline'
                    size='lg'
                    className='w-full justify-start gap-3'
                    onClick={() => handleLogin(provider.name)}
                    disabled={isAnyLoading}
                    aria-label={`${UI_TEXT.CONTINUE_WITH} ${provider.display_name}`}
                  >
                    <Icon className='h-5 w-5' />
                    {isLoading ? (
                      <span>
                        {UI_TEXT.CONNECTING_TO} {provider.display_name}...
                      </span>
                    ) : (
                      <span>
                        {UI_TEXT.CONTINUE_WITH} {provider.display_name}
                      </span>
                    )}
                  </Button>
                );
              })
            ) : (
              <div className='text-muted-foreground text-center'>
                No authentication providers available
              </div>
            )}
          </div>

          <Separator className='my-4' />

          {/* Privacy notice */}
          <div className='text-muted-foreground text-center text-sm'>
            <p>{UI_TEXT.PRIVACY_NOTICE}</p>
            <p className='mt-2'>{UI_TEXT.PRIVATE_APP_NOTICE}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <LoginContent />
    </Suspense>
  );
}
