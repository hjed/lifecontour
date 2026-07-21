'use client';

/**
 * Preview-only context harness for design-sync.
 *
 * The `ui/` primitives render standalone, but the shared app chrome (Header,
 * Sidebar, UserMenu, Breadcrumb, ActivityFeed) reads from contexts that only
 * exist inside a running Next.js app: the App Router, TanStack Query, and the
 * app's own AuthProvider / SidebarProvider. Outside those, `useSearchParams()`
 * and `usePathname()` return null and `useRouter()` throws.
 *
 * This module supplies stand-ins so those components render as they really do.
 * It mocks *context and network*, never component behaviour — every component
 * in the bundle is the repo's own unmodified code.
 *
 * It is a preview harness, not application code: nothing here is imported by
 * the app, and it is excluded from the component list in config.json.
 */

// MUST stay first — see ds-entry.ts. This module is a separate bundle entry, so
// it needs the `process` global installed ahead of its own Next.js imports too.
import './process-shim';

import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from 'next-themes';
import { AppRouterContext } from 'next/dist/shared/lib/app-router-context.shared-runtime';
import type { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime';
import {
  PathnameContext,
  SearchParamsContext,
  PathParamsContext,
} from 'next/dist/shared/lib/hooks-client-context.shared-runtime';
import { AuthProvider } from '../src/lib/auth/AuthProvider';
import { SidebarProvider } from '../src/contexts/SidebarContext';
import { TooltipProvider } from '../src/components/ui/tooltip';

/**
 * The signed-in user every preview renders as. `AuthContext` is not exported
 * from AuthProvider, so the only way to drive it into an authenticated state is
 * through the session request it makes on mount — hence the fetch stub below
 * rather than a hand-built context value.
 */
const PREVIEW_USER = {
  id: 'preview-user',
  email: 'alex.taylor@example.com',
  name: 'Alex Taylor',
  provider: 'google',
  provider_id: 'preview',
  created_at: '2024-03-02T09:15:00Z',
  last_login: '2026-07-21T08:30:00Z',
};

// Matches API_ENDPOINTS.AUTH.SESSION in src/lib/constants.ts.
const SESSION_URL = '/api/auth/status';

/**
 * Answer the session check locally and let every other request through
 * untouched. Installed at import time so it is in place before AuthProvider's
 * mount-time query fires.
 */
function installSessionStub() {
  const g = globalThis as typeof globalThis & { __dsSessionStub?: boolean };
  if (g.__dsSessionStub) return;
  g.__dsSessionStub = true;

  const realFetch = globalThis.fetch?.bind(globalThis);
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    if (url.includes(SESSION_URL)) {
      return new Response(
        JSON.stringify({ authenticated: true, user: PREVIEW_USER }),
        { status: 200, headers: { 'content-type': 'application/json' } }
      );
    }
    if (!realFetch) {
      return new Response('{}', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    return realFetch(input, init);
  };
}

installSessionStub();

/** No-op App Router. Navigation is meaningless in a static preview. */
const previewRouter: AppRouterInstance = {
  push: () => {},
  replace: () => {},
  refresh: () => {},
  back: () => {},
  forward: () => {},
  prefetch: () => {},
};

interface DesignSyncProviderProps {
  readonly children: React.ReactNode;
  /** Route the chrome should present as active. */
  readonly pathname?: string;
}

/**
 * Wraps every preview card. Order mirrors src/lib/providers.tsx (Query → Theme
 * → Auth), with the Next router contexts added outside and the app's own
 * SidebarProvider plus a TooltipProvider inside.
 */
export function DesignSyncProvider({
  children,
  pathname = '/journals',
}: DesignSyncProviderProps) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        // Previews are static and offline: never retry, never refetch, and
        // don't log expected failures to the console.
        defaultOptions: {
          queries: {
            retry: false,
            refetchOnWindowFocus: false,
            refetchOnReconnect: false,
            staleTime: Infinity,
          },
          mutations: { retry: false },
        },
      })
  );
  const searchParams = React.useMemo(() => new URLSearchParams(), []);

  return (
    <AppRouterContext.Provider value={previewRouter}>
      <PathnameContext.Provider value={pathname}>
        <SearchParamsContext.Provider value={searchParams}>
          <PathParamsContext.Provider value={{}}>
            <QueryClientProvider client={queryClient}>
              <ThemeProvider
                attribute='class'
                defaultTheme='light'
                enableSystem={false}
              >
                <AuthProvider>
                  <SidebarProvider>
                    <TooltipProvider>{children}</TooltipProvider>
                  </SidebarProvider>
                </AuthProvider>
              </ThemeProvider>
            </QueryClientProvider>
          </PathParamsContext.Provider>
        </SearchParamsContext.Provider>
      </PathnameContext.Provider>
    </AppRouterContext.Provider>
  );
}
