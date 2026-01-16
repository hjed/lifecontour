/**
 * Tests for InlineEditHeading component.
 *
 * Tests the heading-specific inline editing component including semantic HTML,
 * accessibility, and integration with InlineEditField.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InlineEditHeading } from '@/components/journals/InlineEditHeading';
import * as useInlineEditModule from '@/hooks/useInlineEdit';

// Mock the useInlineEdit hook
const mockUseInlineEdit = {
  value: 'Test Heading',
  displayValue: 'Test Heading',
  isEditing: false,
  isLoading: false,
  error: null as string | null,
  startEdit: jest.fn(),
  cancelEdit: jest.fn(),
  saveEdit: jest.fn(),
  setValue: jest.fn(),
  handleKeyDown: jest.fn(),
};

jest.mock('@/hooks/useInlineEdit', () => ({
  useInlineEdit: jest.fn(() => mockUseInlineEdit),
}));

// Mock toast notifications
jest.mock('sonner', () => ({
  toast: {
    error: jest.fn(),
    success: jest.fn(),
  },
}));

describe('InlineEditHeading', () => {
  const defaultProps = {
    value: 'Test Heading',
    onSave: jest.fn(),
    placeholder: 'Click to edit heading',
    'data-testid': 'inline-edit-heading',
  };

  beforeEach(() => {
    jest.clearAllMocks();
    // Reset mock implementation
    Object.assign(mockUseInlineEdit, {
      value: 'Test Heading',
      displayValue: 'Test Heading',
      isEditing: false,
      isLoading: false,
      error: null,
      startEdit: jest.fn(),
      cancelEdit: jest.fn(),
      saveEdit: jest.fn(),
      setValue: jest.fn(),
      handleKeyDown: jest.fn(),
    });
  });

  describe('view mode', () => {
    it('should render as h1 by default', () => {
      render(<InlineEditHeading {...defaultProps} />);

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toBeInTheDocument();
      expect(heading).toHaveTextContent('Test Heading');
    });

    it('should render as specified heading level', () => {
      render(<InlineEditHeading {...defaultProps} level={3} />);

      const heading = screen.getByRole('heading', { level: 3 });
      expect(heading).toBeInTheDocument();
      expect(heading).toHaveTextContent('Test Heading');
    });

    it('should render placeholder when value is empty', () => {
      mockUseInlineEdit.displayValue = '';
      render(<InlineEditHeading {...defaultProps} value='' />);

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveTextContent('Click to edit heading');
      expect(heading).toHaveClass('text-muted-foreground');
    });

    it('should enter edit mode when clicked', async () => {
      const user = userEvent.setup();
      render(<InlineEditHeading {...defaultProps} />);

      const heading = screen.getByRole('heading', { level: 1 });
      await user.click(heading);

      expect(mockUseInlineEdit.startEdit).toHaveBeenCalled();
    });

    it('should enter edit mode when Enter key is pressed', async () => {
      const user = userEvent.setup();
      render(<InlineEditHeading {...defaultProps} />);

      const heading = screen.getByRole('heading', { level: 1 });
      heading.focus();
      await user.keyboard('{Enter}');

      expect(mockUseInlineEdit.startEdit).toHaveBeenCalled();
    });

    it('should enter edit mode when Space key is pressed', async () => {
      const user = userEvent.setup();
      render(<InlineEditHeading {...defaultProps} />);

      const heading = screen.getByRole('heading', { level: 1 });
      heading.focus();
      await user.keyboard(' ');

      expect(mockUseInlineEdit.startEdit).toHaveBeenCalled();
    });

    it('should have proper accessibility attributes', () => {
      render(
        <InlineEditHeading {...defaultProps} aria-label='Edit journal title' />
      );

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveAttribute('aria-label', 'Edit journal title');
      expect(heading).toHaveAttribute('tabIndex', '0');
    });

    it('should not be clickable when disabled', async () => {
      const user = userEvent.setup();
      render(<InlineEditHeading {...defaultProps} disabled />);

      const heading = screen.getByRole('heading', { level: 1 });
      await user.click(heading);

      expect(mockUseInlineEdit.startEdit).not.toHaveBeenCalled();
      expect(heading).toHaveAttribute('tabIndex', '-1');
    });

    it('should have proper styling when disabled', () => {
      render(<InlineEditHeading {...defaultProps} disabled />);

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveClass('cursor-not-allowed', 'opacity-50');
    });
  });

  describe('edit mode', () => {
    beforeEach(() => {
      mockUseInlineEdit.isEditing = true;
    });

    it('should render input field in edit mode', () => {
      render(<InlineEditHeading {...defaultProps} />);

      const input = screen.getByRole('textbox');
      expect(input).toBeInTheDocument();
      expect(input).toHaveValue('Test Heading');
    });

    it('should not render heading element in edit mode', () => {
      render(<InlineEditHeading {...defaultProps} />);

      expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    });

    it('should show save and cancel buttons in edit mode', () => {
      render(<InlineEditHeading {...defaultProps} />);

      expect(screen.getByLabelText('Save changes')).toBeInTheDocument();
      expect(screen.getByLabelText('Cancel changes')).toBeInTheDocument();
    });

    it('should call setValue when input value changes', async () => {
      const user = userEvent.setup();
      render(<InlineEditHeading {...defaultProps} />);

      const input = screen.getByRole('textbox');
      await user.type(input, ' Updated');

      expect(mockUseInlineEdit.setValue).toHaveBeenCalled();
    });

    it('should call saveEdit when save button is clicked', async () => {
      const user = userEvent.setup();
      render(<InlineEditHeading {...defaultProps} />);

      const saveButton = screen.getByLabelText('Save changes');
      await user.click(saveButton);

      expect(mockUseInlineEdit.saveEdit).toHaveBeenCalled();
    });

    it('should call cancelEdit when cancel button is clicked', async () => {
      const user = userEvent.setup();
      render(<InlineEditHeading {...defaultProps} />);

      const cancelButton = screen.getByLabelText('Cancel changes');
      await user.click(cancelButton);

      expect(mockUseInlineEdit.cancelEdit).toHaveBeenCalled();
    });

    it('should display error message when error exists', () => {
      mockUseInlineEdit.error = 'Heading is required';
      render(<InlineEditHeading {...defaultProps} />);

      expect(screen.getByText('Heading is required')).toBeInTheDocument();
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    it('should apply error styling to input when error exists', () => {
      mockUseInlineEdit.error = 'Heading is required';
      render(<InlineEditHeading {...defaultProps} />);

      const input = screen.getByRole('textbox');
      expect(input).toHaveClass('border-destructive');
    });

    it('should disable input and buttons when loading', () => {
      mockUseInlineEdit.isLoading = true;
      render(<InlineEditHeading {...defaultProps} />);

      const input = screen.getByRole('textbox');
      const saveButton = screen.getByLabelText('Save changes');
      const cancelButton = screen.getByLabelText('Cancel changes');

      expect(input).toBeDisabled();
      expect(saveButton).toBeDisabled();
      expect(cancelButton).toBeDisabled();
    });
  });

  describe('validation', () => {
    it('should pass validation function to useInlineEdit hook', () => {
      const validation = jest.fn();
      render(<InlineEditHeading {...defaultProps} validation={validation} />);

      // The validation function should be passed to useInlineEdit
      // We can verify this by checking the mock was called with it
      expect(useInlineEditModule.useInlineEdit).toHaveBeenCalledWith(
        'Test Heading',
        defaultProps.onSave,
        validation,
        { showErrorToast: false }
      );
    });
  });
});
