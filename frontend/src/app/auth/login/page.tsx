'use client';

/**
 * Login page with OAuth provider options.
 *
 * Implements dedicated login page as per user requirements
 * with Australian English localization and accessibility.
 */

import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
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
import { OAuthProvider, OAUTH_PROVIDERS } from '@/types/auth';
import { UI_TEXT } from '@/lib/constants';
import { GitBranch, Key } from 'lucide-react';

// OAuth provider icons
const ProviderIcons = {
  [OAuthProvider.GITHUB]: GitBranch,
  [OAuthProvider.MICROSOFT]: Key, // Using Key as placeholder
  [OAuthProvider.DISCORD]: Key, // Using Key as placeholder
  [OAuthProvider.GENERIC]: Key,
};

// Component that uses useSearchParams - needs to be wrapped in Suspense
function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { state, login } = useAuth();
  const [loadingProvider, setLoadingProvider] = useState<OAuthProvider | null>(
    null
  );

  // Get redirect URL from query params
  const redirectTo = searchParams.get('redirect') || '/';

  // Clear loading state when auth state changes
  useEffect(() => {
    if (!state.isLoading) {
      setLoadingProvider(null);
    }
  }, [state.isLoading]);

  // Handle OAuth login
  const handleLogin = (provider: OAuthProvider) => {
    setLoadingProvider(provider);
    login(provider);
    // Redirect happens in AuthProvider after successful OAuth
    // Error handling is done in AuthProvider's onError callback
    // Loading state will be cleared when mutation completes
  };

  // Redirect if already authenticated
  if (state.isAuthenticated) {
    // Type assertion for Next.js router - redirectTo is always a valid route
    router.replace(redirectTo as never);
    return null;
  }

  return (
    <main className='container mx-auto flex min-h-screen items-center justify-center px-4 py-8'>
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
            {Object.entries(OAUTH_PROVIDERS).map(([provider, config]) => {
              const Icon = ProviderIcons[provider as OAuthProvider];
              const isLoading = loadingProvider === provider;
              const isAnyLoading = loadingProvider !== null;

              return (
                <Button
                  key={provider}
                  variant='outline'
                  size='lg'
                  className='w-full justify-start gap-3'
                  onClick={() => handleLogin(provider as OAuthProvider)}
                  disabled={isAnyLoading}
                  aria-label={`${UI_TEXT.CONTINUE_WITH} ${config.name}`}
                >
                  <Icon className='h-5 w-5' />
                  {isLoading ? (
                    <span>
                      {UI_TEXT.CONNECTING_TO} {config.name}...
                    </span>
                  ) : (
                    <span>
                      {UI_TEXT.CONTINUE_WITH} {config.name}
                    </span>
                  )}
                </Button>
              );
            })}
          </div>

          <Separator className='my-4' />

          {/* Privacy notice */}
          <div className='text-muted-foreground text-center text-sm'>
            <p>{UI_TEXT.PRIVACY_NOTICE}</p>
            <p className='mt-2'>{UI_TEXT.PRIVATE_APP_NOTICE}</p>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <LoginContent />
    </Suspense>
  );
}
