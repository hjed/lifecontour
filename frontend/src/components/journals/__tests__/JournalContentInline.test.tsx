/**
 * Tests for JournalContentInline component.
 *
 * Tests the journal content inline editing behavior using a simple textarea,
 * including save/cancel functionality and integration with the useInlineEdit hook.
 * Note: Markdown rendering/preview will be added in a future enhancement.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalContentInline } from '@/components/journals/JournalContentInline';
import { createMockUseInlineEdit } from '../test-helpers';

// Mock the useInlineEdit hook
const mockUseInlineEdit = createMockUseInlineEdit();

jest.mock('@/hooks/useInlineEdit', () => ({
  useInlineEdit: jest.fn(() => mockUseInlineEdit),
}));

describe('JournalContentInline', () => {
  const mockOnSave = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    // Reset mock implementation
    Object.assign(mockUseInlineEdit, createMockUseInlineEdit());
  });

  describe('View Mode', () => {
    it('renders content in view mode', () => {
      render(<JournalContentInline value='test content' onSave={mockOnSave} />);

      expect(screen.getByText('test content')).toBeInTheDocument();
    });

    it('displays placeholder when content is empty', () => {
      Object.assign(mockUseInlineEdit, {
        value: '',
        displayValue: '',
      });

      render(
        <JournalContentInline
          value=''
          onSave={mockOnSave}
          placeholder='Add content'
        />
      );

      expect(screen.getByText('Add content')).toBeInTheDocument();
    });

    it('enters edit mode when clicked', async () => {
      const user = userEvent.setup();
      render(<JournalContentInline value='test content' onSave={mockOnSave} />);

      const button = screen.getByRole('button');
      await user.click(button);

      expect(mockUseInlineEdit.startEdit).toHaveBeenCalled();
    });

    it('applies custom className', () => {
      render(
        <JournalContentInline
          value='test content'
          onSave={mockOnSave}
          className='custom-class'
          data-testid='content'
        />
      );

      const container = screen.getByTestId('content');
      expect(container).toHaveClass('custom-class');
    });
  });

  describe('Edit Mode', () => {
    beforeEach(() => {
      Object.assign(mockUseInlineEdit, {
        isEditing: true,
      });
    });

    it('renders textarea in edit mode', () => {
      render(<JournalContentInline value='test content' onSave={mockOnSave} />);

      expect(screen.getByRole('textbox')).toBeInTheDocument();
    });

    it('shows save and cancel buttons in edit mode', () => {
      render(
        <JournalContentInline
          value='test content'
          onSave={mockOnSave}
          data-testid='content'
        />
      );

      expect(screen.getByTestId('content-save')).toBeInTheDocument();
      expect(screen.getByTestId('content-cancel')).toBeInTheDocument();
    });

    it('calls setValue when textarea changes', async () => {
      const user = userEvent.setup();
      render(<JournalContentInline value='test content' onSave={mockOnSave} />);

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, ' more text');

      expect(mockUseInlineEdit.setValue).toHaveBeenCalled();
    });

    it('calls saveEdit when save button clicked', async () => {
      const user = userEvent.setup();
      render(
        <JournalContentInline
          value='test content'
          onSave={mockOnSave}
          data-testid='content'
        />
      );

      const saveButton = screen.getByTestId('content-save');
      await user.click(saveButton);

      expect(mockUseInlineEdit.saveEdit).toHaveBeenCalled();
    });

    it('calls cancelEdit when cancel button clicked', async () => {
      const user = userEvent.setup();
      render(
        <JournalContentInline
          value='test content'
          onSave={mockOnSave}
          data-testid='content'
        />
      );

      const cancelButton = screen.getByTestId('content-cancel');
      await user.click(cancelButton);

      expect(mockUseInlineEdit.cancelEdit).toHaveBeenCalled();
    });

    it('shows loading state when saving', () => {
      Object.assign(mockUseInlineEdit, {
        isLoading: true,
      });

      render(<JournalContentInline value='test content' onSave={mockOnSave} />);

      expect(screen.getByText('Saving...')).toBeInTheDocument();
    });

    it('displays error message when present', () => {
      Object.assign(mockUseInlineEdit, {
        error: 'Save failed',
      });

      render(
        <JournalContentInline
          value='test content'
          onSave={mockOnSave}
          data-testid='content'
        />
      );

      expect(screen.getByText('Save failed')).toBeInTheDocument();
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    it('has proper ARIA labels in view mode', () => {
      render(
        <JournalContentInline
          value='test content'
          onSave={mockOnSave}
          aria-label='Journal content'
        />
      );

      const button = screen.getByRole('button');
      expect(button).toHaveAttribute('aria-label', 'Journal content');
    });

    it('has proper ARIA attributes in edit mode', () => {
      Object.assign(mockUseInlineEdit, {
        isEditing: true,
        error: 'Error message',
      });

      render(
        <JournalContentInline
          value='test content'
          onSave={mockOnSave}
          data-testid='content'
        />
      );

      const textarea = screen.getByRole('textbox');
      expect(textarea).toHaveAttribute('aria-invalid', 'true');
      expect(textarea).toHaveAttribute('aria-describedby', 'content-error');
    });
  });
});
