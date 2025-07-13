/**
 * Test utilities for placeholder pages (Coming Soon pages).
 *
 * Provides reusable test setup and assertions for pages that show
 * "Coming Soon" content with consistent structure and behavior.
 */

import { render, screen } from '@testing-library/react';
import { useRouter, usePathname, useParams } from 'next/navigation';
import { useAuth } from '@/lib/auth/AuthProvider';

// Mock Next.js navigation hooks
jest.mock('next/navigation', () => ({
  useRouter: jest.fn(),
  usePathname: jest.fn(),
  useParams: jest.fn(),
}));

// Mock the AuthProvider
jest.mock('@/lib/auth/AuthProvider', () => ({
  useAuth: jest.fn(),
}));

const mockUseRouter = useRouter as jest.MockedFunction<typeof useRouter>;
const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;
const mockUseParams = useParams as jest.MockedFunction<typeof useParams>;
const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

// Common mock router setup
export const createMockRouter = () => ({
  push: jest.fn(),
  replace: jest.fn(),
  back: jest.fn(),
  forward: jest.fn(),
  refresh: jest.fn(),
  prefetch: jest.fn(),
});

// Common auth states
export const authStates = {
  authenticated: {
    state: {
      user: { id: '1', email: 'test@example.com' },
      isLoading: false,
      isAuthenticated: true,
      error: undefined,
    },
    login: jest.fn(),
    logout: jest.fn(),
  },
  unauthenticated: {
    state: {
      user: null,
      isLoading: false,
      isAuthenticated: false,
      error: undefined,
    },
    login: jest.fn(),
    logout: jest.fn(),
  },
  loading: {
    state: {
      user: null,
      isLoading: true,
      isAuthenticated: false,
      error: undefined,
    },
    login: jest.fn(),
    logout: jest.fn(),
  },
} as const;

// Page configuration interface
export interface PlaceholderPageConfig {
  /** Page title (h1 heading) */
  readonly title: string;
  /** Page description text */
  readonly description: string;
  /** Default pathname for the page */
  readonly pathname: string;
  /** Implementation details text */
  readonly implementationText: string;
  /** Features description text */
  readonly featuresText: string;
  /** Optional: specific iteration mention (e.g., "ITER1.5-004") */
  readonly iterationText?: string;
  /** Optional: icon color class for testing */
  readonly iconColorClass?: string;
  /** Optional: params for dynamic routes */
  readonly params?: Record<string, string>;
}

/**
 * Setup common mocks for placeholder page tests
 */
export function setupPlaceholderPageMocks(config: PlaceholderPageConfig) {
  beforeEach(() => {
    // Mock Next.js router hooks
    mockUseRouter.mockReturnValue(createMockRouter() as any);
    mockUsePathname.mockReturnValue(config.pathname);
    
    if (config.params) {
      mockUseParams.mockReturnValue(config.params);
    }

    // Mock authenticated user by default
    mockUseAuth.mockReturnValue(authStates.authenticated);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });
}

/**
 * Common test suite for placeholder pages
 */
export function createPlaceholderPageTests(
  PageComponent: React.ComponentType,
  config: PlaceholderPageConfig
) {
  return {
    'renders the page with correct title and description': () => {
      render(<PageComponent />);
      
      // Check main heading
      expect(screen.getByRole('heading', { level: 1, name: config.title })).toBeInTheDocument();
      
      // Check description
      expect(screen.getByText(config.description)).toBeInTheDocument();
    },

    'displays coming soon card': () => {
      render(<PageComponent />);

      // Check card title
      expect(screen.getByText('Coming Soon')).toBeInTheDocument();

      // Check card content - use more flexible text matching for HTML entities
      expect(screen.getByText((content, element) => {
        return content.includes(config.implementationText.replace(/&apos;/g, "'"));
      })).toBeInTheDocument();
      expect(screen.getByText((content, element) => {
        return content.includes(config.featuresText.replace(/&apos;/g, "'"));
      })).toBeInTheDocument();
    },

    'has proper page structure with container and spacing': () => {
      const { container } = render(<PageComponent />);
      
      // Check that the page has proper container structure
      const containerDiv = container.querySelector('.container');
      expect(containerDiv).toBeInTheDocument();
      expect(containerDiv).toHaveClass('mx-auto', 'px-4', 'py-8');
      
      // Check that there's a margin bottom on the header section
      const headerSection = container.querySelector('.mb-6');
      expect(headerSection).toBeInTheDocument();
    },

    'renders within AuthGuard component': () => {
      // Test that unauthenticated users are handled by AuthGuard
      mockUseAuth.mockReturnValue(authStates.unauthenticated);

      render(<PageComponent />);

      // When not authenticated, AuthGuard should handle the redirect
      // The page content should not be rendered
      expect(screen.queryByText(config.title)).not.toBeInTheDocument();
    },

    'shows loading state when auth is loading': () => {
      mockUseAuth.mockReturnValue(authStates.loading);

      render(<PageComponent />);

      // When loading, AuthGuard should show loading state
      // The page content should not be rendered yet
      expect(screen.queryByText(config.title)).not.toBeInTheDocument();
    },

    'has proper semantic HTML structure': () => {
      render(<PageComponent />);
      
      // Check that the main heading is properly structured
      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveTextContent(config.title);
      
      // Check that the description paragraph exists
      const description = screen.getByText(config.description);
      expect(description.tagName.toLowerCase()).toBe('p');
    },

    'has accessible card structure': () => {
      render(<PageComponent />);
      
      // The card should have proper heading structure
      const cardTitle = screen.getByText('Coming Soon');
      expect(cardTitle).toBeInTheDocument();
      
      // The card content should be readable
      const cardContent = screen.getByText(new RegExp(config.implementationText));
      expect(cardContent).toBeInTheDocument();
    },

    // Optional iteration test
    ...(config.iterationText && {
      'mentions the correct iteration for implementation': () => {
        render(<PageComponent />);
        
        // Verify that it mentions the specific iteration
        expect(screen.getByText(new RegExp(config.iterationText!))).toBeInTheDocument();
      },
    }),

    // Optional icon color test
    ...(config.iconColorClass && {
      'uses appropriate icon color': () => {
        const { container } = render(<PageComponent />);
        
        // Check that the icon has the expected color class
        const iconElement = container.querySelector(`.${config.iconColorClass}`);
        expect(iconElement).toBeInTheDocument();
      },
    }),
  };
}

/**
 * Helper for dynamic route pages (like contact groups)
 */
export function createDynamicPlaceholderPageTests(
  PageComponent: React.ComponentType,
  baseConfig: Omit<PlaceholderPageConfig, 'title' | 'description'>,
  dynamicTests: Array<{
    params: Record<string, string>;
    expectedTitle: string;
    expectedDescription: string;
  }>
) {
  const tests: Record<string, () => void> = {};

  dynamicTests.forEach(({ params, expectedTitle, expectedDescription }) => {
    const paramString = Object.entries(params).map(([k, v]) => `${k}=${v}`).join(', ');
    
    tests[`renders correctly with params: ${paramString}`] = () => {
      mockUseParams.mockReturnValue(params);
      
      render(<PageComponent />);
      
      // Check dynamic title and description
      expect(screen.getByRole('heading', { level: 1, name: expectedTitle })).toBeInTheDocument();
      expect(screen.getByText(expectedDescription)).toBeInTheDocument();
    };
  });

  return tests;
}
