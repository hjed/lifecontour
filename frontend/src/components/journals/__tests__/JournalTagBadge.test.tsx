/**
 * Tests for JournalTagBadge component.
 *
 * Tests tag badge display and management functionality.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalTagBadge } from '../JournalTagBadge';
import type { JournalTag } from '@/types/journals';

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
  Select: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid='select'>{children}</div>
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

describe('JournalTagBadge', () => {
  const mockTags: JournalTag[] = [
    { id: '1', name: 'Work', color: '#3b82f6' },
    { id: '2', name: 'Important', color: '#ef4444' },
  ];

  const mockAvailableTags: JournalTag[] = [
    ...mockTags,
    { id: '3', name: 'Personal', color: '#10b981' },
  ];

  const mockOnTagAdd = jest.fn();
  const mockOnTagRemove = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Display Mode', () => {
    it('renders tag badges', () => {
      render(<JournalTagBadge tags={mockTags} />);

      expect(screen.getByText('Work')).toBeInTheDocument();
      expect(screen.getByText('Important')).toBeInTheDocument();
    });

    it('renders empty container when no tags', () => {
      render(<JournalTagBadge tags={[]} />);

      expect(screen.getByTestId('tag-badges')).toBeInTheDocument();
      expect(screen.queryByText(/Work|Important/)).not.toBeInTheDocument();
    });

    it('applies custom className', () => {
      const { container } = render(
        <JournalTagBadge tags={mockTags} className='custom-class' />
      );

      expect(container.firstChild).toHaveClass('custom-class');
    });

    it('has proper test ids for each tag', () => {
      render(<JournalTagBadge tags={mockTags} />);

      expect(screen.getByTestId('tag-badge-1')).toBeInTheDocument();
      expect(screen.getByTestId('tag-badge-2')).toBeInTheDocument();
    });
  });

  describe('Add Tag', () => {
    it('renders add button when onTagAdd is provided', () => {
      render(
        <JournalTagBadge
          tags={mockTags}
          onTagAdd={mockOnTagAdd}
          availableTags={mockAvailableTags}
        />
      );

      expect(screen.getByText('Add Tag')).toBeInTheDocument();
    });

    it('does not render add button when onTagAdd is not provided', () => {
      render(<JournalTagBadge tags={mockTags} />);

      expect(screen.queryByText('Add Tag')).not.toBeInTheDocument();
    });

    it('shows select with available tags', () => {
      render(
        <JournalTagBadge
          tags={mockTags}
          onTagAdd={mockOnTagAdd}
          availableTags={mockAvailableTags}
        />
      );

      expect(screen.getByTestId('select')).toBeInTheDocument();
    });

    it('label has htmlFor attribute for accessibility', () => {
      render(
        <JournalTagBadge
          tags={mockTags}
          onTagAdd={mockOnTagAdd}
          availableTags={mockAvailableTags}
        />
      );

      const label = screen.getByText('Select Tag');
      expect(label).toHaveAttribute('for', 'tag-select');
    });
  });

  describe('Remove Tag', () => {
    it('renders remove button for each tag when onTagRemove is provided', () => {
      render(<JournalTagBadge tags={mockTags} onTagRemove={mockOnTagRemove} />);

      const removeButtons = screen.getAllByLabelText(/Remove tag .+/);
      expect(removeButtons).toHaveLength(2);
    });

    it('calls onTagRemove when remove button is clicked', async () => {
      const user = userEvent.setup();
      render(<JournalTagBadge tags={mockTags} onTagRemove={mockOnTagRemove} />);

      const removeButton = screen.getByLabelText('Remove tag Work');
      await user.click(removeButton);

      expect(mockOnTagRemove).toHaveBeenCalledWith('1');
    });
  });

  describe('Disabled State', () => {
    it('disables remove buttons when disabled prop is true', () => {
      render(
        <JournalTagBadge
          tags={mockTags}
          onTagRemove={mockOnTagRemove}
          disabled={true}
        />
      );

      const removeButtons = screen.getAllByLabelText(/Remove tag .+/);
      removeButtons.forEach(button => {
        expect(button).toBeDisabled();
      });
    });
  });

  describe('Accessibility', () => {
    it('has proper test ids', () => {
      render(<JournalTagBadge tags={mockTags} />);

      expect(screen.getByTestId('tag-badges')).toBeInTheDocument();
    });

    it('has aria labels on remove buttons', () => {
      render(<JournalTagBadge tags={mockTags} onTagRemove={mockOnTagRemove} />);

      expect(screen.getByLabelText('Remove tag Work')).toBeInTheDocument();
      expect(screen.getByLabelText('Remove tag Important')).toBeInTheDocument();
    });
  });
});
