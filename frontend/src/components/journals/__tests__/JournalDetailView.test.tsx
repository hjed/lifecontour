/**
 * Tests for JournalDetailView component.
 *
 * Tests the comprehensive detail view that integrates all relationship components.
 */

import { screen } from '@testing-library/react';
import { JournalDetailView } from '../JournalDetailView';
import {
  createMockJournalWithMetadata,
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
  useMergeJournal: () => ({
    mutateAsync: jest.fn(),
    isPending: false,
  }),
  useUpdateTypeData: () => ({
    mutateAsync: jest.fn(),
    isPending: false,
  }),
  useAddJournalType: () => ({
    mutateAsync: jest.fn(),
    isPending: false,
  }),
  useRemoveJournalType: () => ({
    mutateAsync: jest.fn(),
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
  JournalBreadcrumb: ({ currentTitle }: any) => (
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

jest.mock('../JournalTypeSection', () => ({
  JournalTypeSection: ({ type }: any) => (
    <div data-testid={`type-section-${type}`}>Type Section: {type}</div>
  ),
}));

jest.mock('../JournalTypeManager', () => ({
  JournalTypeManager: ({ currentTypes }: any) => (
    <div data-testid='type-manager'>
      Type Manager: {currentTypes.join(', ')}
    </div>
  ),
}));

jest.mock('@/components/contacts/InlineEditField', () => ({
  InlineEditField: ({ value, 'data-testid': testId }: any) => (
    <div data-testid={testId}>{value}</div>
  ),
}));

jest.mock('../JournalContentInline', () => ({
  JournalContentInline: ({ value, 'data-testid': testId }: any) => (
    <div data-testid={testId}>{value}</div>
  ),
}));

jest.mock('../InlineEditDateRange', () => ({
  InlineEditDateRange: ({ value, 'data-testid': testId }: any) => (
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

    it('does not render children list when no children', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.queryByTestId('children-list')).not.toBeInTheDocument();
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
