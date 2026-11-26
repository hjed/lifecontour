/**
 * Shared test utilities for journal component tests.
 *
 * Provides common mock data, setup functions, and helpers to reduce
 * duplication across journal component test files.
 */

import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JournalType, type JournalResource } from '@/types/journals';
import { PACKING_LIST, createMockTaskRead } from '@/test-utils/tasks';
import {
  TaskLinkRole,
  type JournalTaskAttributes,
  type JournalTaskResource,
  type TaskJournalRef,
} from '@/types/tasks';
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
 * Create a mock journal reference as a task's read model carries one.
 *
 * `date` is an ISO date already resolved in the user's timezone, never an
 * instant — the same shape `TaskJournalRef` documents.
 */
export function createMockTaskJournalRef(
  partial?: Partial<TaskJournalRef>
): TaskJournalRef {
  return {
    id: 1,
    title: 'Test Journal',
    date: '2025-01-15',
    cancelled: false,
    ...partial,
  };
}

/**
 * Create a mock task resource as a journal's listing returns one.
 *
 * Defaults to the simplest task a journal can hold: not done, not lapsed, no
 * contacts, due in the journal that created it. Every test states only the
 * attributes it is about.
 */
export function createMockJournalTask(
  partial?: Partial<JournalTaskAttributes> & { id?: string }
): JournalTaskResource {
  const { link_roles = [TaskLinkRole.DUE], ...readAttributes } = partial ?? {};
  const { id, attributes } = createMockTaskRead({
    creating_journal_id: 1,
    due_journal_id: 1,
    creating_journal: createMockTaskJournalRef(),
    due_journal: createMockTaskJournalRef(),
    ...readAttributes,
  });

  return { type: 'tasks', id, attributes: { ...attributes, link_roles } };
}

/**
 * Create a mock task on a list, as a journal's listing returns one.
 *
 * Defaults to a list task in no journal at all — no creating journal and no
 * due journal — so each test names the one journal it reaches the listing
 * through. It is on list 7. A list task never lapses, so `lapsed` stays false.
 */
export function createMockListTask(
  partial?: Partial<JournalTaskAttributes> & { id?: string }
): JournalTaskResource {
  return createMockJournalTask({
    task_list_id: PACKING_LIST.id,
    task_list: PACKING_LIST,
    creating_journal_id: null,
    due_journal_id: null,
    creating_journal: null,
    due_journal: null,
    link_roles: [TaskLinkRole.CREATED],
    ...partial,
  });
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
