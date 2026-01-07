/**
 * Tests for JournalDetail component.
 *
 * Tests the main journal detail view including layout, sections,
 * inline editing integration, and responsive behavior.
 */

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalDetail } from '@/components/journals/JournalDetail';
import {
  createMockJournalWithMetadata,
  renderWithQueryClient,
} from '../test-helpers';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

// Mock the API hook
const mockMutateAsync = jest.fn();
jest.mock('@/lib/api/journals', () => ({
  useUpdateJournalField: () => ({
    mutateAsync: mockMutateAsync,
  }),
}));

// Mock child components
jest.mock('@/components/journals/JournalIdentityInline', () => ({
  JournalIdentityInline: ({ journal }: any) => (
    <div data-testid='journal-identity'>{journal.attributes.title}</div>
  ),
}));

jest.mock('@/components/journals/JournalContentInline', () => ({
  JournalContentInline: ({ value }: any) => (
    <div data-testid='journal-content'>{value}</div>
  ),
}));

describe('JournalDetail', () => {
  const mockJournal = createMockJournalWithMetadata();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Loading State', () => {
    it('renders skeleton when loading', () => {
      const { container } = renderWithQueryClient(
        <JournalDetail journal={mockJournal} isLoading={true} />
      );

      // Should show skeleton loaders (using data-slot attribute)
      const skeletons = container.querySelectorAll('[data-slot="skeleton"]');
      expect(skeletons.length).toBeGreaterThan(0);
    });
  });

  describe('Error State', () => {
    it('renders error message when error occurs', () => {
      const error = new Error('Failed to load journal');
      renderWithQueryClient(
        <JournalDetail journal={mockJournal} error={error} />
      );

      expect(screen.getByText(/Failed to load journal/i)).toBeInTheDocument();
    });
  });

  describe('Content Rendering', () => {
    it('renders journal detail with all sections', () => {
      renderWithQueryClient(<JournalDetail journal={mockJournal} />);

      expect(screen.getByTestId('journal-detail')).toBeInTheDocument();
      expect(screen.getByTestId('journal-identity')).toBeInTheDocument();
      expect(screen.getByTestId('journal-content')).toBeInTheDocument();
    });

    it('renders back button', () => {
      renderWithQueryClient(<JournalDetail journal={mockJournal} />);

      expect(screen.getByTestId('back-button')).toBeInTheDocument();
      expect(screen.getByText('Back')).toBeInTheDocument();
    });

    it('renders delete button', () => {
      renderWithQueryClient(<JournalDetail journal={mockJournal} />);

      expect(screen.getByTestId('delete-button')).toBeInTheDocument();
    });

    it('displays calendar color bar', () => {
      const { container } = renderWithQueryClient(
        <JournalDetail journal={mockJournal} />
      );

      const colorBar = container.querySelector('[style*="background-color"]');
      expect(colorBar).toBeInTheDocument();
      expect(colorBar).toHaveStyle({ backgroundColor: '#10b981' });
    });

    it('renders type badges', () => {
      renderWithQueryClient(<JournalDetail journal={mockJournal} />);

      expect(screen.getByTestId('type-badge-NOTE')).toBeInTheDocument();
    });

    it('renders calendar badge', () => {
      renderWithQueryClient(<JournalDetail journal={mockJournal} />);

      expect(screen.getByTestId('calendar-badge')).toBeInTheDocument();
      expect(screen.getByText('Personal')).toBeInTheDocument();
    });

    it('renders tag badges', () => {
      renderWithQueryClient(<JournalDetail journal={mockJournal} />);

      expect(screen.getByTestId('tag-badge-1')).toBeInTheDocument();
      expect(screen.getByTestId('tag-badge-2')).toBeInTheDocument();
      expect(screen.getByText('Work')).toBeInTheDocument();
      expect(screen.getByText('Important')).toBeInTheDocument();
    });

    it('renders timestamps', () => {
      renderWithQueryClient(<JournalDetail journal={mockJournal} />);

      expect(screen.getByText(/Created:/)).toBeInTheDocument();
      expect(screen.getByText(/Updated:/)).toBeInTheDocument();
    });
  });

  describe('Navigation', () => {
    it('navigates back when back button clicked', async () => {
      const user = userEvent.setup();
      renderWithQueryClient(<JournalDetail journal={mockJournal} />);

      const backButton = screen.getByTestId('back-button');
      await user.click(backButton);

      expect(mockPush).toHaveBeenCalledWith('/journals');
    });
  });

  describe('Accessibility', () => {
    it('has proper ARIA labels on buttons', () => {
      renderWithQueryClient(<JournalDetail journal={mockJournal} />);

      expect(screen.getByLabelText('Back to journals')).toBeInTheDocument();
      expect(screen.getByLabelText('Delete journal')).toBeInTheDocument();
    });

    it('applies custom className', () => {
      renderWithQueryClient(
        <JournalDetail journal={mockJournal} className='custom-class' />
      );

      expect(screen.getByTestId('journal-detail')).toHaveClass('custom-class');
    });
  });
});
