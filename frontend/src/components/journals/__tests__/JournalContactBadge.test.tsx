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
  AttendeeStatus,
  ContactEventRole,
  type JournalContactRelationship,
} from '@/types/journals';
import type { ContactResource } from '@/types/contacts';

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
  Select: ({ children, value, onValueChange }: any) => (
    <button
      type='button'
      data-testid='select'
      data-value={value}
      onClick={() => {
        // Just mock changing value for tests
        if (onValueChange) {
          onValueChange(value === 'NO_STATUS' ? 'ATTENDING' : 'NO_STATUS');
        }
      }}
    >
      {children}
    </button>
  ),
  SelectTrigger: ({ children }: any) => (
    <div data-testid='select-trigger'>{children}</div>
  ),
  SelectValue: ({ placeholder }: any) => <span>{placeholder}</span>,
  SelectContent: ({ children }: any) => <div>{children}</div>,
  SelectItem: ({ children, value }: any) => (
    <div data-value={value} data-testid={`select-item-${value}`}>
      {children}
    </div>
  ),
}));

const mockSearchSelectContact: ContactResource = {
  type: 'contacts',
  id: '3',
  attributes: {
    first_name: 'Bob',
    last_name: 'Johnson',
    middle_name: '',
    nick_name: '',
    is_favourite: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    contact_methods: [],
    addresses: [],
    notes: [],
    relationships: [],
  },
};

jest.mock('@/components/contacts/ContactSearchCombobox', () => ({
  ContactSearchCombobox: ({ onSelect, disabled, inputId }: any) => (
    <div>
      <input id={inputId} placeholder='Search for a contact...' readOnly />
      <button
        type='button'
        data-testid='contact-search-combobox'
        disabled={disabled}
        onClick={() => onSelect(mockSearchSelectContact)}
      >
        Search contacts
      </button>
    </div>
  ),
}));

describe('JournalContactBadge', () => {
  const mockContacts: JournalContactRelationship[] = [
    {
      id: '1',
      name: 'John Doe',
      relationship_type: JournalContactRelationshipType.PARTICIPANT,
      status: AttendeeStatus.ATTENDING,
      role: ContactEventRole.ORGANISER,
    },
    {
      id: '2',
      name: 'Jane Smith',
      relationship_type: JournalContactRelationshipType.MENTION,
      status: AttendeeStatus.MAYBE,
      role: null,
    },
  ];

  const mockOnContactAdd = jest.fn();
  const mockOnContactRemove = jest.fn();
  const mockOnRelationshipUpdate = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Display Mode', () => {
    it('renders contact badges with proper links and accessibility labels', () => {
      render(<JournalContactBadge contacts={mockContacts} />);

      // Verify John Doe
      expect(screen.getByText('John Doe')).toBeInTheDocument();
      const johnLink = screen.getByRole('link', { name: 'View John Doe' });
      expect(johnLink).toBeInTheDocument();
      expect(johnLink).toHaveAttribute('href', '/contacts/1');

      // Verify Jane Smith
      expect(screen.getByText('Jane Smith')).toBeInTheDocument();
      const janeLink = screen.getByRole('link', { name: 'View Jane Smith' });
      expect(janeLink).toBeInTheDocument();
      expect(janeLink).toHaveAttribute('href', '/contacts/2');
    });

    it('renders relationship type labels', () => {
      render(<JournalContactBadge contacts={mockContacts} />);

      expect(screen.getByText('(PARTICIPANT)')).toBeInTheDocument();
      expect(screen.getByText('(MENTION)')).toBeInTheDocument();
    });

    it('renders status indicators with correct colors and tooltips', () => {
      render(<JournalContactBadge contacts={mockContacts} />);
      const attendingStatus = screen.getByTestId('contact-status-1');
      expect(attendingStatus).toHaveClass('bg-green-500');
      expect(attendingStatus).toHaveAttribute(
        'aria-label',
        'Status: ATTENDING'
      );

      const maybeStatus = screen.getByTestId('contact-status-2');
      expect(maybeStatus).toHaveClass('bg-amber-500');
      expect(maybeStatus).toHaveAttribute('aria-label', 'Status: MAYBE');
    });

    it('renders role badges', () => {
      render(<JournalContactBadge contacts={mockContacts} />);
      const roleBadge = screen.getByTestId('contact-role-1');
      expect(roleBadge).toHaveTextContent('ORG');
      expect(roleBadge).toHaveAttribute('aria-label', 'Role: ORGANISER');

      expect(screen.queryByTestId('contact-role-2')).not.toBeInTheDocument();
    });

    it('renders empty container when no contacts', () => {
      render(<JournalContactBadge contacts={[]} />);

      expect(screen.getByTestId('contact-badges')).toBeInTheDocument();
      expect(screen.queryByText(/PARTICIPANT|MENTION/)).not.toBeInTheDocument();
    });
  });

  describe('Add Contact', () => {
    it('adds the selected contact from the search combobox', async () => {
      const user = userEvent.setup();
      mockOnContactAdd.mockResolvedValue(undefined);

      render(
        <JournalContactBadge
          contacts={mockContacts}
          onContactAdd={mockOnContactAdd}
        />
      );

      await user.click(screen.getByTestId('contact-search-combobox'));
      await user.click(screen.getByRole('button', { name: 'Add' }));

      expect(mockOnContactAdd).toHaveBeenCalledWith(
        ['3'],
        JournalContactRelationshipType.PARTICIPANT,
        null,
        null
      );
    });
  });

  describe('Remove Contact', () => {
    it('calls onContactRemove when remove button is clicked', async () => {
      const user = userEvent.setup();
      render(
        <JournalContactBadge
          contacts={mockContacts}
          onContactRemove={mockOnContactRemove}
        />
      );

      const removeButton = screen.getByTestId('remove-contact-1');
      await user.click(removeButton);

      expect(mockOnContactRemove).toHaveBeenCalledWith('1');
    });
  });

  describe('Edit Contact Status and Role', () => {
    it('renders pencil icon for eligible contacts (Participant/Invitee) when onRelationshipUpdate is provided', () => {
      render(
        <JournalContactBadge
          contacts={mockContacts}
          onRelationshipUpdate={mockOnRelationshipUpdate}
        />
      );
      // John Doe is PARTICIPANT, should have edit button
      expect(screen.getByTestId('edit-contact-1')).toBeInTheDocument();

      // Jane Smith is MENTION, should NOT have edit button
      expect(screen.queryByTestId('edit-contact-2')).not.toBeInTheDocument();
    });

    it('opens popover and triggers update on save', async () => {
      const user = userEvent.setup();
      render(
        <JournalContactBadge
          contacts={mockContacts}
          onRelationshipUpdate={mockOnRelationshipUpdate}
        />
      );

      // Open Popover
      await user.click(screen.getByTestId('edit-contact-1'));

      // Save using Save button
      const saveButton = screen.getByRole('button', { name: 'Save' });
      await user.click(saveButton);

      expect(mockOnRelationshipUpdate).toHaveBeenCalledWith(
        '1',
        JournalContactRelationshipType.PARTICIPANT,
        AttendeeStatus.ATTENDING, // untouched initial value
        ContactEventRole.ORGANISER // untouched initial value
      );
    });
  });

  describe('Accessibility', () => {
    it('has proper test ids', () => {
      render(<JournalContactBadge contacts={mockContacts} />);
      expect(screen.getByTestId('contact-badges')).toBeInTheDocument();
    });
  });
});
