'use client';

/**
 * Application providers for TanStack Query, authentication, and other global state.
 *
 * This component wraps the entire application with necessary providers
 * following the AI guidelines for clean dependency injection.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { ThemeProvider } from 'next-themes';
import { useState } from 'react';
import { Toaster } from '@/components/ui/sonner';
import { AuthProvider } from '@/lib/auth/AuthProvider';
import { QUERY_CLIENT_DEFAULT_OPTIONS } from '@/lib/query-client-options';

interface ProvidersProps {
  children: React.ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  // Create QueryClient with optimized settings for AI assistant understanding
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: QUERY_CLIENT_DEFAULT_OPTIONS })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider
        attribute='class'
        defaultTheme='system'
        enableSystem
        disableTransitionOnChange
      >
        <AuthProvider>
          {children}

          {/* Toast notifications */}
          {/* Colours come from ui/sonner.tsx, which maps sonner's
              --normal-* variables onto the app's theme tokens. */}
          <Toaster position='top-right' toastOptions={{ duration: 4000 }} />

          {/* React Query DevTools - only in development */}
          {process.env.NODE_ENV === 'development' && (
            <ReactQueryDevtools initialIsOpen={false} />
          )}
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
