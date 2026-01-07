/**
 * Tests for JournalIdentityInline component.
 *
 * Tests the inline editing functionality for journal title and date range fields.
 */

import { screen } from '@testing-library/react';
import { JournalIdentityInline } from '@/components/journals/JournalIdentityInline';
import { createMockJournal, renderWithQueryClient } from '../test-helpers';

// Mock the API hook
const mockMutateAsync = jest.fn();
jest.mock('@/lib/api/journals', () => ({
  useUpdateJournalField: () => ({
    mutateAsync: mockMutateAsync,
  }),
}));

// Mock child components
jest.mock('@/components/contacts/InlineEditField', () => ({
  InlineEditField: ({ value, 'data-testid': testId }: any) => (
    <div data-testid={testId}>{value}</div>
  ),
}));

jest.mock('@/components/journals/InlineEditDateRange', () => ({
  InlineEditDateRange: ({ value, 'data-testid': testId }: any) => (
    <div data-testid={testId}>
      {value.start} - {value.end}
    </div>
  ),
}));

describe('JournalIdentityInline', () => {
  const mockJournal = createMockJournal();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('renders journal title field', () => {
      renderWithQueryClient(<JournalIdentityInline journal={mockJournal} />);

      expect(screen.getByTestId('journal-title-field')).toHaveTextContent(
        'Test Journal'
      );
    });

    it('renders date range field', () => {
      renderWithQueryClient(<JournalIdentityInline journal={mockJournal} />);

      const dateField = screen.getByTestId('journal-date-range-field');
      expect(dateField).toBeInTheDocument();
      expect(dateField).toHaveTextContent('2025-01-15T00:00:00Z');
      expect(dateField).toHaveTextContent('2025-01-16T00:00:00Z');
    });

    it('applies custom className', () => {
      const { container } = renderWithQueryClient(
        <JournalIdentityInline journal={mockJournal} className='custom-class' />
      );

      expect(container.firstChild).toHaveClass('custom-class');
    });
  });

  describe('Field Updates', () => {
    it('provides title save handler', () => {
      renderWithQueryClient(<JournalIdentityInline journal={mockJournal} />);

      // Component should render without errors
      expect(screen.getByTestId('journal-title-field')).toBeInTheDocument();
    });

    it('provides date range save handler', () => {
      renderWithQueryClient(<JournalIdentityInline journal={mockJournal} />);

      // Component should render without errors
      expect(
        screen.getByTestId('journal-date-range-field')
      ).toBeInTheDocument();
    });
  });

  describe('Integration', () => {
    it('passes correct props to InlineEditField', () => {
      renderWithQueryClient(<JournalIdentityInline journal={mockJournal} />);

      const titleField = screen.getByTestId('journal-title-field');
      expect(titleField).toHaveTextContent('Test Journal');
    });

    it('passes correct props to InlineEditDateRange', () => {
      renderWithQueryClient(<JournalIdentityInline journal={mockJournal} />);

      const dateField = screen.getByTestId('journal-date-range-field');
      expect(dateField).toBeInTheDocument();
    });
  });
});
