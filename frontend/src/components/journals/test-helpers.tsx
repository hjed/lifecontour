/**
 * Shared test utilities for journal component tests.
 *
 * Provides common mock data, setup functions, and helpers to reduce
 * duplication across journal component test files.
 */

import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JournalType, type JournalResource } from '@/types/journals';
import {
  DisplayJournal,
  transformJournalForDisplay,
} from '@/utils/journalTransformers';

/**
 * Create a mock journal resource with sensible defaults.
 * All fields can be overridden via the partial parameter.
 */
export function createMockJournal(
  partial?: Partial<JournalResource['attributes']>
): JournalResource {
  return {
    type: 'journals',
    id: '1',
    attributes: {
      title: 'Test Journal',
      content: 'Test content',
      event_date_range: {
        start: '2025-01-15T00:00:00Z',
        end: '2025-01-16T00:00:00Z',
      },
      types: [JournalType.NOTE],
      type_data: {},
      contacts: [],
      tags: [],
      calendar: null,
      parent: null,
      children_count: 0,
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
      ...partial,
    },
  };
}

/**
 * Create a mock journal with rich metadata (tags, calendar, contacts).
 */
export function createMockJournalWithMetadata(): JournalResource {
  return createMockJournal({
    title: 'Test Journal',
    content: 'Test content with some details',
    tags: [
      { id: '1', name: 'Work', color: '#3b82f6' },
      { id: '2', name: 'Important', color: '#ef4444' },
    ],
    calendar: {
      id: 'cal1',
      name: 'Personal',
      color: '#10b981',
    },
  });
}

/**
 * Create a QueryClient configured for testing.
 * Disables retries to make tests faster and more predictable.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

/**
 * Render a component wrapped in QueryClientProvider.
 * Creates a fresh QueryClient for each render to ensure test isolation.
 */
export function renderWithQueryClient(component: React.ReactElement) {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>{component}</QueryClientProvider>
  );
}

/**
 * Common mock setup for journal API hooks.
 * Returns mock functions that can be used in assertions.
 */
export function setupJournalApiMocks() {
  const mockMutateAsync = jest.fn();

  jest.mock('@/lib/api/journals', () => ({
    useUpdateJournalField: () => ({
      mutateAsync: mockMutateAsync,
    }),
  }));

  return { mockMutateAsync };
}

/**
 * Common beforeEach setup for journal tests.
 * Clears all mocks to ensure test isolation.
 */
export function setupJournalTest() {
  beforeEach(() => {
    jest.clearAllMocks();
  });
}

/**
 * Create a mock useInlineEdit hook return value.
 * Useful for testing components that use inline editing.
 */
export function createMockUseInlineEdit(
  overrides?: Partial<{
    value: string;
    displayValue: string;
    isEditing: boolean;
    isLoading: boolean;
    error: string | null;
    startEdit: jest.Mock;
    cancelEdit: jest.Mock;
    saveEdit: jest.Mock;
    setValue: jest.Mock;
    handleKeyDown: jest.Mock;
  }>
) {
  return {
    value: 'test content',
    displayValue: 'test content',
    isEditing: false,
    isLoading: false,
    error: null as string | null,
    startEdit: jest.fn(),
    cancelEdit: jest.fn(),
    saveEdit: jest.fn(),
    setValue: jest.fn(),
    handleKeyDown: jest.fn(),
    ...overrides,
  };
}

/**
 * Transform JournalResource to DisplayJournal for testing.
 * Uses the shared transformation utility to maintain consistency.
 */
export function toDisplayJournal(
  journal: JournalResource,
  shouldUseSearch = false
): DisplayJournal {
  return transformJournalForDisplay(journal, shouldUseSearch);
}
