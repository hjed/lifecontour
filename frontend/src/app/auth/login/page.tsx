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
import { useAuth } from '@/lib/auth-context';
import { apiClient } from '@/lib/api-client';
import { GitBranch, User } from 'lucide-react';

interface OAuthProvider {
  name: string;
  display_name: string;
  icon_url?: string;
}

// OAuth provider icons
const providerIcons: Record<
  string,
  React.ComponentType<{ className?: string }>
> = {
  github: GitBranch,
  microsoft: User,
  discord: User,
};

// Component that uses useSearchParams - needs to be wrapped in Suspense
function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated, login } = useAuth();
  const [providers, setProviders] = useState<OAuthProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadingProvider, setLoadingProvider] = useState<string | null>(null);

  // Get redirect URL from query params
  const redirectTo = searchParams.get('redirect') || '/';

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      router.replace(redirectTo as any);
    }
  }, [isAuthenticated, router, redirectTo]);

  // Fetch available OAuth providers
  useEffect(() => {
    const fetchProviders = async () => {
      try {
        setLoading(true);
        const response = await apiClient.getAuthProviders();

        if (response.errors) {
          setError(
            response.errors[0]?.detail ||
              'Failed to load authentication providers'
          );
        } else if (response.data) {
          setProviders(response.data.providers);
        }
      } catch (err) {
        setError('Failed to load authentication providers');
        console.error('Failed to fetch providers:', err);
      } finally {
        setLoading(false);
      }
    };

    if (!isAuthenticated) {
      fetchProviders();
    }
  }, [isAuthenticated]);

  // Handle OAuth login
  const handleLogin = (providerName: string) => {
    setLoadingProvider(providerName);
    login(providerName, redirectTo);
  };

  // Redirect if already authenticated
  if (isAuthenticated) {
    return null;
  }

  return (
    <main className='container mx-auto flex min-h-screen items-center justify-center px-4 py-8'>
      <Card className='w-full max-w-md' data-testid='login-form' role='form'>
        <CardHeader className='space-y-1 text-center'>
          <h1 className='text-2xl font-bold tracking-tight'>Welcome Back</h1>
          <CardDescription>
            Sign in to your Personal CRM account
          </CardDescription>
        </CardHeader>

        <CardContent className='space-y-4'>
          {/* Error message */}
          {error && (
            <Alert variant='destructive' data-testid='auth-error'>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {loading ? (
            <div className='space-y-3'>
              <div className='bg-muted h-10 animate-pulse rounded' />
              <div className='bg-muted h-10 animate-pulse rounded' />
            </div>
          ) : providers.length > 0 ? (
            <div className='space-y-3'>
              <p className='text-muted-foreground text-center text-sm'>
                Choose your preferred sign-in method:
              </p>
              {providers.map(provider => {
                const IconComponent = providerIcons[provider.name] || User;
                const isLoading = loadingProvider === provider.name;
                const isAnyLoading = loadingProvider !== null;

                return (
                  <Button
                    key={provider.name}
                    variant='outline'
                    size='lg'
                    className='w-full justify-start gap-3'
                    onClick={() => handleLogin(provider.name)}
                    disabled={isAnyLoading}
                    data-testid={`oauth-provider-${provider.name}`}
                    aria-label={`Continue with ${provider.display_name}`}
                  >
                    <IconComponent className='h-5 w-5' />
                    {isLoading ? (
                      <span>Connecting to {provider.display_name}...</span>
                    ) : (
                      <span>Continue with {provider.display_name}</span>
                    )}
                  </Button>
                );
              })}
            </div>
          ) : (
            <Alert data-testid='auth-error'>
              <AlertDescription>
                No authentication providers are currently available. Please
                contact your administrator.
              </AlertDescription>
            </Alert>
          )}

          {/* Privacy notice */}
          <div className='text-muted-foreground text-center text-sm'>
            <p>
              By signing in, you agree to our terms of service and privacy
              policy.
            </p>
            <p className='mt-2'>
              This is a private application for personal use.
            </p>
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
