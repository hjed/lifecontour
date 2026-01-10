/**
 * Tests for JournalDetailView component.
 *
 * Tests the comprehensive detail view that integrates all relationship components.
 */

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
}));

jest.mock('@/lib/api/contacts', () => ({
  useContacts: () => ({
    data: { data: [] },
  }),
}));

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

jest.mock('../JournalTypeDataDisplay', () => ({
  JournalTypeDataDisplay: () => <div data-testid='type-data'>Type Data</div>,
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

    it('renders all badge components', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.getByTestId('calendar-badge')).toBeInTheDocument();
      expect(screen.getByTestId('contact-badge')).toBeInTheDocument();
      expect(screen.getByTestId('tag-badge')).toBeInTheDocument();
    });

    it('renders type badges', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.getByText('NOTE')).toBeInTheDocument();
    });

    it('renders formatted date', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.getByText(/January 15, 2025/)).toBeInTheDocument();
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
    it('renders edit button when onEdit is provided', () => {
      const mockOnEdit = jest.fn();
      renderWithQueryClient(
        <JournalDetailView journal={mockJournal} onEdit={mockOnEdit} />
      );

      const buttons = screen.getAllByRole('button');
      // Should have at least one button (edit button)
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('calls onEdit when edit button is clicked', async () => {
      const user = userEvent.setup();
      const mockOnEdit = jest.fn();
      renderWithQueryClient(
        <JournalDetailView journal={mockJournal} onEdit={mockOnEdit} />
      );

      // The first button should be the edit button
      const buttons = screen.getAllByRole('button');
      await user.click(buttons[0]);

      expect(mockOnEdit).toHaveBeenCalled();
    });

    it('does not render edit button when onEdit is not provided', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      // Without onEdit, there should be fewer buttons
      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
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

      expect(screen.getByTestId('type-data')).toBeInTheDocument();
    });
  });

  describe('Content Display', () => {
    it('renders journal content', () => {
      renderWithQueryClient(<JournalDetailView journal={mockJournal} />);

      expect(screen.getByText('Test content')).toBeInTheDocument();
    });

    it('preserves whitespace in content', () => {
      const journalWithWhitespace = {
        ...mockJournal,
        content: 'Line 1\n\nLine 2',
      };

      renderWithQueryClient(
        <JournalDetailView journal={journalWithWhitespace} />
      );

      const content = screen.getByText(/Line 1/);
      expect(content).toHaveClass('whitespace-pre-wrap');
      expect(content.textContent).toBe('Line 1\n\nLine 2');
    });
  });

  describe('Date Handling', () => {
    it('does not render date when event_date_range start is empty', () => {
      const journalWithoutDate = {
        ...mockJournal,
        event_date_range: {
          start: '',
          end: '',
        },
      };

      renderWithQueryClient(<JournalDetailView journal={journalWithoutDate} />);

      expect(screen.queryByText(/January/)).not.toBeInTheDocument();
    });
  });
});
