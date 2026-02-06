/**
 * Tests for JournalContactBadge component.
 *
 * Tests contact badge display and management functionality.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalContactBadge } from '../JournalContactBadge';
import {
  JournalContactRelationshipType,
  type JournalContactRelationship,
} from '@/types/journals';

// Mock Popover component
jest.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: any) => <div>{children}</div>,
  PopoverTrigger: ({ children }: any) => <div>{children}</div>,
  PopoverContent: ({ children }: any) => (
    <div data-testid='popover-content'>{children}</div>
  ),
}));

// Mock Select component
jest.mock('@/components/ui/select', () => ({
  Select: ({ children }: any) => <div data-testid='select'>{children}</div>,
  SelectTrigger: ({ children }: any) => <div>{children}</div>,
  SelectValue: ({ placeholder }: any) => <span>{placeholder}</span>,
  SelectContent: ({ children }: any) => <div>{children}</div>,
  SelectItem: ({ children }: any) => <div>{children}</div>,
}));

describe('JournalContactBadge', () => {
  const mockContacts: JournalContactRelationship[] = [
    {
      id: '1',
      name: 'John Doe',
      relationship_type: JournalContactRelationshipType.PARTICIPANT,
    },
    {
      id: '2',
      name: 'Jane Smith',
      relationship_type: JournalContactRelationshipType.MENTION,
    },
  ];

  const mockAvailableContacts = [
    { id: 1, name: 'John Doe' },
    { id: 2, name: 'Jane Smith' },
    { id: 3, name: 'Bob Johnson' },
  ];

  const mockOnContactAdd = jest.fn();
  const mockOnContactRemove = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Display Mode', () => {
    it('renders contact badges', () => {
      render(<JournalContactBadge contacts={mockContacts} />);

      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.getByText('Jane Smith')).toBeInTheDocument();
    });

    it('renders relationship type labels', () => {
      render(<JournalContactBadge contacts={mockContacts} />);

      expect(screen.getByText('(PARTICIPANT)')).toBeInTheDocument();
      expect(screen.getByText('(MENTION)')).toBeInTheDocument();
    });

    it('renders empty container when no contacts', () => {
      render(<JournalContactBadge contacts={[]} />);

      expect(screen.getByTestId('contact-badges')).toBeInTheDocument();
      expect(screen.queryByText(/PARTICIPANT|MENTION/)).not.toBeInTheDocument();
    });

    it('applies custom className', () => {
      const { container } = render(
        <JournalContactBadge contacts={mockContacts} className='custom-class' />
      );

      expect(container.firstChild).toHaveClass('custom-class');
    });
  });

  describe('Add Contact', () => {
    it('renders add button when onContactAdd is provided', () => {
      render(
        <JournalContactBadge
          contacts={mockContacts}
          onContactAdd={mockOnContactAdd}
          availableContacts={mockAvailableContacts}
        />
      );

      expect(screen.getByText('Add Contact')).toBeInTheDocument();
    });

    it('does not render add button when onContactAdd is not provided', () => {
      render(<JournalContactBadge contacts={mockContacts} />);

      expect(screen.queryByText('Add Contact')).not.toBeInTheDocument();
    });
  });

  describe('Remove Contact', () => {
    it('renders remove button for each contact when onContactRemove is provided', () => {
      render(
        <JournalContactBadge
          contacts={mockContacts}
          onContactRemove={mockOnContactRemove}
        />
      );

      const removeButtons = screen.getAllByLabelText(/Remove .+/);
      expect(removeButtons).toHaveLength(2);
    });

    it('calls onContactRemove when remove button is clicked', async () => {
      const user = userEvent.setup();
      render(
        <JournalContactBadge
          contacts={mockContacts}
          onContactRemove={mockOnContactRemove}
        />
      );

      const removeButton = screen.getByLabelText('Remove John Doe');
      await user.click(removeButton);

      expect(mockOnContactRemove).toHaveBeenCalledWith('1');
    });
  });

  describe('Disabled State', () => {
    it('disables remove buttons when disabled prop is true', () => {
      render(
        <JournalContactBadge
          contacts={mockContacts}
          onContactRemove={mockOnContactRemove}
          disabled={true}
        />
      );

      const removeButtons = screen.getAllByLabelText(/Remove .+/);
      removeButtons.forEach(button => {
        expect(button).toBeDisabled();
      });
    });
  });

  describe('Accessibility', () => {
    it('has proper test ids', () => {
      render(<JournalContactBadge contacts={mockContacts} />);

      expect(screen.getByTestId('contact-badges')).toBeInTheDocument();
    });

    it('has aria labels on remove buttons', () => {
      render(
        <JournalContactBadge
          contacts={mockContacts}
          onContactRemove={mockOnContactRemove}
        />
      );

      expect(screen.getByLabelText('Remove John Doe')).toBeInTheDocument();
      expect(screen.getByLabelText('Remove Jane Smith')).toBeInTheDocument();
    });
  });
});
