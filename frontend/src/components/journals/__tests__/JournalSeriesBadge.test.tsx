/**
 * Tests for JournalSeriesBadge component.
 *
 * Tests series badge display, membership management and inline creation.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalSeriesBadge } from '../JournalSeriesBadge';
import type { JournalSeries, JournalSeriesRef } from '@/types/journals';

// Mock Popover component
jest.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
  PopoverTrigger: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
  PopoverContent: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid='popover-content'>{children}</div>
  ),
}));

// Mock Select component
jest.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
  }: {
    children?: React.ReactNode;
    onValueChange?: (value: string) => void;
  }) => (
    <div data-testid='select'>
      <button
        type='button'
        data-testid='select-first-option'
        onClick={() => onValueChange?.('series-3')}
      >
        pick first
      </button>
      {children}
    </div>
  ),
  SelectTrigger: ({
    children,
    id,
  }: {
    children?: React.ReactNode;
    id?: string;
  }) => (
    <div id={id} data-testid='select-trigger'>
      {children}
    </div>
  ),
  SelectValue: ({ placeholder }: { placeholder?: string }) => (
    <span>{placeholder}</span>
  ),
  SelectContent: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
  SelectItem: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

describe('JournalSeriesBadge', () => {
  const mockSeries: JournalSeriesRef[] = [
    { id: 'series-1', name: 'Physio appointments' },
    { id: 'series-2', name: 'Weekly standup' },
  ];

  const mockAvailableSeries: JournalSeries[] = [
    { id: 'series-1', name: 'Physio appointments' },
    { id: 'series-2', name: 'Weekly standup' },
    { id: 'series-3', name: 'Book club' },
  ];

  const mockOnSeriesAdd = jest.fn();
  const mockOnSeriesRemove = jest.fn();
  const mockOnSeriesCreate = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Display Mode', () => {
    it('renders series badges with links to the series page', () => {
      render(<JournalSeriesBadge series={mockSeries} />);

      expect(screen.getByText('Physio appointments')).toBeInTheDocument();
      expect(screen.getByText('Weekly standup')).toBeInTheDocument();

      const link = screen.getByRole('link', { name: /Physio appointments/ });
      expect(link).toHaveAttribute('href', '/journals/series/series-1');
    });

    it('renders empty container when no series', () => {
      render(<JournalSeriesBadge series={[]} />);

      expect(screen.getByTestId('series-badges')).toBeInTheDocument();
      expect(screen.queryByText(/Physio|standup/)).not.toBeInTheDocument();
    });

    it('has proper test ids for each series', () => {
      render(<JournalSeriesBadge series={mockSeries} />);

      expect(screen.getByTestId('series-badge-series-1')).toBeInTheDocument();
      expect(screen.getByTestId('series-badge-series-2')).toBeInTheDocument();
    });
  });

  describe('Add to Series', () => {
    it('renders add button when onSeriesAdd is provided', () => {
      render(
        <JournalSeriesBadge
          series={mockSeries}
          onSeriesAdd={mockOnSeriesAdd}
          availableSeries={mockAvailableSeries}
        />
      );

      expect(screen.getByText('Add to Series')).toBeInTheDocument();
    });

    it('does not render add button when onSeriesAdd is not provided', () => {
      render(<JournalSeriesBadge series={mockSeries} />);

      expect(screen.queryByText('Add to Series')).not.toBeInTheDocument();
    });

    it('adds the selected existing series', async () => {
      const user = userEvent.setup();
      render(
        <JournalSeriesBadge
          series={mockSeries}
          onSeriesAdd={mockOnSeriesAdd}
          availableSeries={mockAvailableSeries}
        />
      );

      await user.click(screen.getByTestId('select-first-option'));
      await user.click(screen.getByRole('button', { name: 'Add' }));

      expect(mockOnSeriesAdd).toHaveBeenCalledWith('series-3');
    });

    it('creates a new series from the popover input', async () => {
      const user = userEvent.setup();
      render(
        <JournalSeriesBadge
          series={mockSeries}
          onSeriesAdd={mockOnSeriesAdd}
          onSeriesCreate={mockOnSeriesCreate}
          availableSeries={mockAvailableSeries}
        />
      );

      const input = screen.getByPlaceholderText('New series name');
      await user.type(input, 'Dentist visits');
      await user.click(screen.getByRole('button', { name: 'Create & Add' }));

      expect(mockOnSeriesCreate).toHaveBeenCalledWith('Dentist visits');
    });
  });

  describe('Remove from Series', () => {
    it('calls onSeriesRemove when remove button is clicked', async () => {
      const user = userEvent.setup();
      render(
        <JournalSeriesBadge
          series={mockSeries}
          onSeriesRemove={mockOnSeriesRemove}
        />
      );

      await user.click(
        screen.getByLabelText('Remove from series Physio appointments')
      );

      expect(mockOnSeriesRemove).toHaveBeenCalledWith('series-1');
    });

    it('disables remove buttons when disabled prop is true', () => {
      render(
        <JournalSeriesBadge
          series={mockSeries}
          onSeriesRemove={mockOnSeriesRemove}
          disabled={true}
        />
      );

      const removeButtons = screen.getAllByLabelText(/Remove from series .+/);
      removeButtons.forEach(button => {
        expect(button).toBeDisabled();
      });
    });
  });
});
