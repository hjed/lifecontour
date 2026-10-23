/**
 * The application's QueryClient, built in one place so a test can use exactly
 * what production uses — defaults and global mutation callbacks alike.
 */

import { MutationCache, QueryClient } from '@tanstack/react-query';
import { QUERY_CLIENT_DEFAULT_OPTIONS } from '@/lib/query-client-options';
import { handleWriteConflict } from '@/lib/write-conflicts';

export function createAppQueryClient(): QueryClient {
  const queryClient: QueryClient = new QueryClient({
    defaultOptions: QUERY_CLIENT_DEFAULT_OPTIONS,
    mutationCache: new MutationCache({
      onError: (error, variables, _onMutateResult, mutation) =>
        handleWriteConflict(queryClient, error, variables, mutation),
    }),
  });
  return queryClient;
}
