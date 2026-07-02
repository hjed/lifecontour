/**
 * Tests for JournalDetailView component.
 *
 * Tests the comprehensive detail view that integrates all relationship components.
 */

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { JournalDetailView } from '../JournalDetailView';
import {
  createMockJournalWithMetadata,
  createTestQueryClient,
  renderWithQueryClient,
} from '../test-helpers';
import { JournalType } from '@/types/journals';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

// Mock API hooks
const mockUpdateJournal = jest.fn();
const mockDeleteJournal = jest.fn();
const mockAddContact = jest.fn();
const mockRemoveContact = jest.fn();
const mockAddTag = jest.fn();
const mockRemoveTag = jest.fn();
const mockUpdateField = jest.fn();
const mockAddType = jest.fn();
const mockRemoveType = jest.fn();

jest.mock('@/lib/api/journals', () => ({
  useUpdateJournal: () => ({
    mutateAsync: mockUpdateJournal,
    isPending: false,
  }),
  useDeleteJournal: () => ({
    mutateAsync: mockDeleteJournal,
    isPending: false,
  }),
  useAddContactRelationship: () => ({
    mutateAsync: mockAddContact,
  }),
  useRemoveContactRelationship: () => ({
    mutateAsync: mockRemoveContact,
  }),
  useUpdateContactRelationship: () => ({
    mutateAsync: jest.fn(),
  }),
  useAddJournalTag: () => ({
    mutateAsync: mockAddTag,
  }),
  useRemoveJournalTag: () => ({
    mutateAsync: mockRemoveTag,
  }),
  useJournalTags: () => ({
    data: { data: [] },
  }),
  useUpdateJournalField: () => ({
    mutateAsync: mockUpdateField,
    isPending: false,
  }),
  useJournal: () => ({
    data: { data: null },
    isPending: false,
  }),
  useMergeJournal: () => ({
    mutateAsync: jest.fn(),
    isPending: false,
  }),
  useUpdateTypeData: () => ({
    mutateAsync: jest.fn(),
    isPending: false,
  }),
  useAddJournalType: () => ({
    mutateAsync: mockAddType,
    isPending: false,
  }),
  useRemoveJournalType: () => ({
    mutateAsync: mockRemoveType,
    isPending: false,
  }),
  useCalendars: () => ({
    data: { data: [] },
  }),
}));

jest.mock('@/lib/api/contacts', () => ({
  useContacts: jest.fn(() => ({
    data: { data: [] },
  })),
}));

const mockUseContacts = jest.mocked(
  jest.requireMock('@/lib/api/contacts').useContacts
);

// Mock child components
jest.mock('../JournalBreadcrumb', () => ({
  JournalBreadcrumb: ({ currentTitle }: { currentTitle?: string }) => (
    <div data-testid='breadcrumb'>{currentTitle}</div>
  ),
}));

jest.mock('../JournalCalendarBadge', () => ({
  JournalCalendarBadge: () => <div data-testid='calendar-badge'>Calendar</div>,
}));

jest.mock('../JournalContactBadge', () => ({
  JournalContactBadge: () => <div data-testid='contact-badge'>Contacts</div>,
}));

jest.mock('../JournalTagBadge', () => ({
  JournalTagBadge: () => <div data-testid='tag-badge'>Tags</div>,
}));

jest.mock('../JournalChildrenList', () => ({
  JournalChildrenList: () => <div data-testid='children-list'>Children</div>,
}));

// The activity feed has its own dedicated tests; mock it here so this view's
// tests don't depend on the journal history data hook.
jest.mock('../ActivityFeed', () => ({
  ActivityFeed: ({ journalId }: { journalId?: string }) => (
    <div data-testid='activity-feed-mock'>Activity: {journalId}</div>
  ),
}));

jest.mock('../JournalTypeSection', () => ({
  JournalTypeSection: ({
    type,
    onSave,
  }: {
    type?: string;
    onSave?: (type: string, data: Record<string, unknown>) => Promise<void>;
  }) => (
    <div data-testid={`type-section-${type}`}>
      Type Section: {type}
      <button
        data-testid={`type-section-save-${type}`}
        onClick={() => onSave?.(type as string, { gear_item_id: 'gear-1' })}
      >
        save
      </button>
    </div>
  ),
}));

jest.mock('../JournalTypeManager', () => ({
  JournalTypeManager: ({
    currentTypes = [],
    onTypeAdd,
    onTypeRemove,
  }: {
    currentTypes?: string[];
    onTypeAdd?: (type: string) => Promise<void>;
    onTypeRemove?: (type: string) => Promise<void>;
  }) => (
    <div data-testid='type-manager'>
      Type Manager: {currentTypes.join(', ')}
      <button
        data-testid='add-gear-usage'
        onClick={() => onTypeAdd?.('gear_usage')}
      >
        add gear usage
      </button>
      <button
        data-testid='remove-gear-usage'
        onClick={() => onTypeRemove?.('gear_usage')}
      >
        remove gear usage
      </button>
    </div>
  ),
}));

jest.mock('@/components/contacts/InlineEditField', () => ({
  InlineEditField: ({
    value,
    'data-testid': testId,
  }: {
    value?: string;
    'data-testid'?: string;
  }) => <div data-testid={testId}>{value}</div>,
}));

jest.mock('../JournalContentInline', () => ({
  JournalContentInline: ({
    value,
    'data-testid': testId,
  }: {
    value?: string;
    'data-testid'?: string;
  }) => <div data-testid={testId}>{value}</div>,
}));

jest.mock('../InlineEditDateRange', () => ({
  InlineEditDateRange: ({
    value,
    'data-testid': testId,
  }: {
    value?: { start?: string; end?: string };
    'data-testid'?: string;
  }) => (
    <div data-testid={testId}>
      {value?.start} - {value?.end}
    </div>
  ),
}));

describe('JournalDetailView', () => {
  const mockJournal = {
    ...createMockJournalWithMetadata(),
    id: '1',
    title: 'Test Journal',
    content: 'Test content',
    types: [JournalType.NOTE],
    type_data: {},
    contacts: [],
    tags: [],
    calendar: null,
    parent: null,
    children: undefined,
    children_count: 0,
    event_date_range: {
      start: '2025-01-15T00:00:00Z',
      end: '2025-01-15T00:00:00Z',
    },
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('renders detail view with all sections', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.getByTestId('journal-detail-view')).toBeInTheDocument();
      expect(screen.getByTestId('breadcrumb')).toBeInTheDocument();
      expect(screen.getAllByText('Test Journal').length).toBeGreaterThan(0);
      expect(screen.getByText('Test content')).toBeInTheDocument();
    });

    it('does not preload contacts for the contact relationship picker', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(mockUseContacts).not.toHaveBeenCalled();
    });

    it('renders all badge components', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.getByTestId('calendar-badge')).toBeInTheDocument();
      expect(screen.getByTestId('contact-badge')).toBeInTheDocument();
      expect(screen.getByTestId('tag-badge')).toBeInTheDocument();
    });

    it('renders type manager', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.getByTestId('type-manager')).toBeInTheDocument();
      expect(screen.getByText('Type Manager: note')).toBeInTheDocument();
    });

    it('renders date range field', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      // The date range is now shown in an inline editable field
      expect(
        screen.getByTestId('journal-date-range-field')
      ).toBeInTheDocument();
    });

    it('applies custom className', () => {
      renderWithQueryClient(
        <JournalDetailView journal={mockJournal} className='custom-class' />
      );

      expect(screen.getByTestId('journal-detail-view')).toHaveClass(
        'custom-class'
      );
    });
  });

  describe('Action Buttons', () => {
    it('renders delete button', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      const deleteButton = screen.getByLabelText('Delete journal');
      expect(deleteButton).toBeInTheDocument();
    });
  });

  describe('Children List', () => {
    it('renders children list when children exist', () => {
      const journalWithChildren = {
        ...mockJournal,
        children: [
          {
            id: 'child-1',
            title: 'Child Journal',
            types: [JournalType.NOTE],
            event_date_range: null,
          },
        ],
      };

      renderWithQueryClient(
        <JournalDetailView journal={journalWithChildren} />
      );

      expect(screen.getByTestId('children-list')).toBeInTheDocument();
    });

    it('always renders children list section for add child functionality', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.getByTestId('children-list')).toBeInTheDocument();
    });
  });

  describe('Pending types requiring initial data (gear usage)', () => {
    it('adds gear usage to a local pending editor without persisting immediately', async () => {
      const user = userEvent.setup();
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      // Not present before adding.
      expect(
        screen.queryByTestId('type-section-gear_usage')
      ).not.toBeInTheDocument();

      await user.click(screen.getByTestId('add-gear-usage'));

      // A pending editor renders, but nothing is persisted to the backend yet.
      expect(screen.getByTestId('type-section-gear_usage')).toBeInTheDocument();
      expect(mockAddType).not.toHaveBeenCalled();
    });

    it('persists gear usage with its initial data when the pending editor is saved', async () => {
      const user = userEvent.setup();
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      await user.click(screen.getByTestId('add-gear-usage'));
      await user.click(screen.getByTestId('type-section-save-gear_usage'));

      expect(mockAddType).toHaveBeenCalledWith({
        journalId: '1',
        journalType: JournalType.GEAR_USAGE,
        typeData: { gear_item_id: 'gear-1' },
      });
    });

    it('keeps the section visible after save until the refetch persists it', async () => {
      const user = userEvent.setup();
      // Simulate a successful-but-not-yet-refetched add: the mutation resolves
      // but journal.types has not updated yet.
      mockAddType.mockResolvedValueOnce(undefined);
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      await user.click(screen.getByTestId('add-gear-usage'));
      await user.click(screen.getByTestId('type-section-save-gear_usage'));

      // The pending section must not disappear during the invalidate → refetch
      // window, otherwise it looks like the save failed.
      expect(screen.getByTestId('type-section-gear_usage')).toBeInTheDocument();
    });

    it('does not duplicate the section once the journal reports it persisted', async () => {
      const user = userEvent.setup();
      const { rerender } = renderWithQueryClient(
        <JournalDetailView journal={mockJournal} />
      );

      await user.click(screen.getByTestId('add-gear-usage'));
      await user.click(screen.getByTestId('type-section-save-gear_usage'));

      // The refetch lands: the journal now carries the persisted gear usage type.
      const persistedJournal = {
        ...mockJournal,
        types: [JournalType.NOTE, JournalType.GEAR_USAGE],
        type_data: { gear_usage: { gear_item_id: 'gear-1' } },
      };
      rerender(
        <QueryClientProvider client={createTestQueryClient()}>
          <JournalDetailView journal={persistedJournal} />
        </QueryClientProvider>
      );

      // Exactly one gear usage section — displayedTypes dedupes the still-present
      // pending entry against the now-persisted type.
      expect(screen.getAllByTestId('type-section-gear_usage')).toHaveLength(1);
    });

    it('removes a pending gear usage editor locally without a backend call', async () => {
      const user = userEvent.setup();
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      await user.click(screen.getByTestId('add-gear-usage'));
      expect(screen.getByTestId('type-section-gear_usage')).toBeInTheDocument();

      await user.click(screen.getByTestId('remove-gear-usage'));

      expect(
        screen.queryByTestId('type-section-gear_usage')
      ).not.toBeInTheDocument();
      expect(mockRemoveType).not.toHaveBeenCalled();
    });
  });

  describe('Type Data Display', () => {
    it('renders type data display', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      // Check that type sections are rendered for each type
      expect(screen.getByTestId('type-section-note')).toBeInTheDocument();
    });
  });

  describe('Content Display', () => {
    it('renders journal content', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.getByText('Test content')).toBeInTheDocument();
    });

    it('renders content in inline editable field', () => {
      const journalWithWhitespace = {
        ...mockJournal,
        content: 'Line 1\n\nLine 2',
      };

      renderWithQueryClient(
        <JournalDetailView journal={journalWithWhitespace} />
      );

      // Content is now in an inline editable component
      const content = screen.getByTestId('journal-content');
      expect(content).toBeInTheDocument();
      expect(content.textContent).toBe('Line 1\n\nLine 2');
    });
  });

  describe('Date Handling', () => {
    it('does not render date field when event_date_range is not set', () => {
      const journalWithoutDate = {
        ...mockJournal,
        event_date_range: { start: '', end: '' },
      };

      renderWithQueryClient(<JournalDetailView journal={journalWithoutDate} />);

      expect(
        screen.queryByTestId('journal-date-range-field')
      ).not.toBeInTheDocument();
    });
  });
});
