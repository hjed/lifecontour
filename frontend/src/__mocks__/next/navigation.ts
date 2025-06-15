import type { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime';

// Create mock functions
const mockPush = jest.fn();
const mockReplace = jest.fn();
const mockPrefetch = jest.fn();
const mockBack = jest.fn();
const mockForward = jest.fn();
const mockRefresh = jest.fn();

// Create mock router instance
const mockRouter: Partial<AppRouterInstance> = {
  push: mockPush,
  replace: mockReplace,
  prefetch: mockPrefetch,
  back: mockBack,
  forward: mockForward,
  refresh: mockRefresh,
};

// Export mocked hooks
export const useRouter = jest.fn(() => mockRouter);
export const usePathname = jest.fn(() => '/');
export const useSearchParams = jest.fn(() => new URLSearchParams());
export const useParams = jest.fn(() => ({}));

// Export mock functions for test access
export const __mockRouter = {
  push: mockPush,
  replace: mockReplace,
  prefetch: mockPrefetch,
  back: mockBack,
  forward: mockForward,
  refresh: mockRefresh,
};
