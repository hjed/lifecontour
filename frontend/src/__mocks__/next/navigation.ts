import { createMockAppRouter } from '@/test-utils/mock-router';

// Create mock router instance
const mockRouter = createMockAppRouter();

// Export mocked hooks
export const useRouter = jest.fn(() => mockRouter);
export const usePathname = jest.fn(() => '/');
export const useSearchParams = jest.fn(() => new URLSearchParams());
export const useParams = jest.fn(() => ({}));

// Export the router for test access to its individual mock functions
export const __mockRouter = mockRouter;
