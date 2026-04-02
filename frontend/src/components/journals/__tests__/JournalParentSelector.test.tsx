/**
 * Tests for JournalParentSelector component.
 *
 * Tests the parent journal selection, display, and removal.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalParentSelector } from '../JournalParentSelector';
import type { ParentJournalSummary } from '@/types/journals';

// Mock next/link
jest.mock('next/link', () => {
  const MockLink = ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>;
  MockLink.displayName = 'MockLink';
  return MockLink;
});

// Mock the JournalSearchCombobox
jest.mock('../JournalSearchCombobox', () => {
  const MockJournalSearchCombobox = ({
    onSelect,
    inputId,
    placeholder,
    excludeJournalId,
  }: {
    onSelect: (journal: { id: string; attributes: { title: string } }) => void;
    inputId?: string;
    placeholder?: string;
    excludeJournalId?: string;
  }) => (
    <div data-testid='journal-search-combobox'>
      <input
        id={inputId}
        placeholder={placeholder}
        data-exclude-id={excludeJournalId}
        onChange={e => {
          if (e.target.value === 'select-parent') {
            onSelect({
              id: '99',
              attributes: { title: 'Selected Parent' },
            } as { id: string; attributes: { title: string } });
          }
        }}
      />
    </div>
  );
  MockJournalSearchCombobox.displayName = 'MockJournalSearchCombobox';
  return { JournalSearchCombobox: MockJournalSearchCombobox };
});

describe('JournalParentSelector', () => {
  const mockParent: ParentJournalSummary = {
    id: '42',
    title: 'Parent Journal Title',
  };

  const mockOnParentChange = jest.fn().mockResolvedValue(undefined);
  const mockOnParentRemove = jest.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('When parent is set', () => {
    it('renders the parent journal title as a link', () => {
      render(
        <JournalParentSelector
          currentJournalId='10'
          parent={mockParent}
          onParentChange={mockOnParentChange}
          onParentRemove={mockOnParentRemove}
        />
      );

      const link = screen.getByText('Parent Journal Title');
      expect(link.closest('a')).toHaveAttribute('href', '/journals/42');
    });

    it('renders a remove button', () => {
      render(
        <JournalParentSelector
          currentJournalId='10'
          parent={mockParent}
          onParentChange={mockOnParentChange}
          onParentRemove={mockOnParentRemove}
        />
      );

      expect(
        screen.getByRole('button', { name: /remove parent/i })
      ).toBeInTheDocument();
    });

    it('calls onParentRemove when remove button is clicked', async () => {
      const user = userEvent.setup();

      render(
        <JournalParentSelector
          currentJournalId='10'
          parent={mockParent}
          onParentChange={mockOnParentChange}
          onParentRemove={mockOnParentRemove}
        />
      );

      const removeButton = screen.getByRole('button', {
        name: /remove parent/i,
      });
      await user.click(removeButton);

      expect(mockOnParentRemove).toHaveBeenCalledTimes(1);
    });

    it('renders a change parent button', () => {
      render(
        <JournalParentSelector
          currentJournalId='10'
          parent={mockParent}
          onParentChange={mockOnParentChange}
          onParentRemove={mockOnParentRemove}
        />
      );

      expect(
        screen.getByRole('button', { name: /change parent/i })
      ).toBeInTheDocument();
    });
  });

  describe('When no parent is set', () => {
    it('renders a "Set Parent" button', () => {
      render(
        <JournalParentSelector
          currentJournalId='10'
          onParentChange={mockOnParentChange}
          onParentRemove={mockOnParentRemove}
        />
      );

      expect(
        screen.getByRole('button', { name: /set parent/i })
      ).toBeInTheDocument();
    });

    it('does not render a parent link', () => {
      render(
        <JournalParentSelector
          currentJournalId='10'
          onParentChange={mockOnParentChange}
          onParentRemove={mockOnParentRemove}
        />
      );

      expect(
        screen.queryByText('Parent Journal Title')
      ).not.toBeInTheDocument();
    });
  });

  describe('Search functionality', () => {
    it('passes currentJournalId as excludeJournalId to the search combobox', async () => {
      const user = userEvent.setup();

      render(
        <JournalParentSelector
          currentJournalId='10'
          onParentChange={mockOnParentChange}
          onParentRemove={mockOnParentRemove}
        />
      );

      // Open the popover
      const setButton = screen.getByRole('button', { name: /set parent/i });
      await user.click(setButton);

      // The search combobox should have the excludeJournalId set
      const searchInput = screen.getByTestId('journal-search-combobox');
      const input = searchInput.querySelector('input');
      expect(input).toHaveAttribute('data-exclude-id', '10');
    });

    it('calls onParentChange when a journal is selected from search', async () => {
      const user = userEvent.setup();

      render(
        <JournalParentSelector
          currentJournalId='10'
          onParentChange={mockOnParentChange}
          onParentRemove={mockOnParentRemove}
        />
      );

      // Open the popover
      const setButton = screen.getByRole('button', { name: /set parent/i });
      await user.click(setButton);

      // Trigger selection
      const input = screen
        .getByTestId('journal-search-combobox')
        .querySelector('input')!;
      await user.type(input, 'select-parent');

      expect(mockOnParentChange).toHaveBeenCalledWith('99');
    });
  });

  describe('Accessibility', () => {
    it('has proper test id', () => {
      render(
        <JournalParentSelector
          currentJournalId='10'
          parent={mockParent}
          onParentChange={mockOnParentChange}
          onParentRemove={mockOnParentRemove}
        />
      );

      expect(screen.getByTestId('parent-selector')).toBeInTheDocument();
    });
  });
});
