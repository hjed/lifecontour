/**
 * Tests for InlineEditField component.
 *
 * Tests the base inline editing component including view/edit states,
 * user interactions, accessibility, and integration with useInlineEdit hook.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InlineEditField } from '@/components/contacts/InlineEditField';

// Mock the useInlineEdit hook
const mockUseInlineEdit = {
  value: 'test value',
  displayValue: 'test value',
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

describe('InlineEditField', () => {
  const defaultProps = {
    value: 'test value',
    onSave: jest.fn(),
    placeholder: 'Enter value',
    'data-testid': 'inline-edit-field',
  };

  beforeEach(() => {
    jest.clearAllMocks();
    // Reset mock implementation
    Object.assign(mockUseInlineEdit, {
      value: 'test value',
      displayValue: 'test value',
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
    it('should render value in view mode', () => {
      render(<InlineEditField {...defaultProps} />);

      expect(screen.getByText('test value')).toBeInTheDocument();
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    });

    it('should render placeholder when value is empty', () => {
      mockUseInlineEdit.displayValue = '';
      render(<InlineEditField {...defaultProps} value='' />);

      expect(screen.getByText('Enter value')).toBeInTheDocument();
      expect(screen.getByText('Enter value')).toHaveClass(
        'text-muted-foreground'
      );
    });

    it('should enter edit mode when clicked', async () => {
      const user = userEvent.setup();
      render(<InlineEditField {...defaultProps} />);

      const viewElement = screen.getByText('test value');
      await user.click(viewElement);

      expect(mockUseInlineEdit.startEdit).toHaveBeenCalled();
    });

    it('should enter edit mode when Enter key is pressed', async () => {
      const user = userEvent.setup();
      render(<InlineEditField {...defaultProps} />);

      const viewElement = screen.getByText('test value');
      viewElement.focus();
      await user.keyboard('{Enter}');

      expect(mockUseInlineEdit.startEdit).toHaveBeenCalled();
    });

    it('should enter edit mode when Space key is pressed', async () => {
      const user = userEvent.setup();
      render(<InlineEditField {...defaultProps} />);

      const viewElement = screen.getByText('test value');
      viewElement.focus();
      await user.keyboard(' ');

      expect(mockUseInlineEdit.startEdit).toHaveBeenCalled();
    });

    it('should have proper accessibility attributes in view mode', () => {
      render(<InlineEditField {...defaultProps} />);

      const viewElement = screen.getByText('test value');
      expect(viewElement.tagName).toBe('BUTTON');
      expect(viewElement).toHaveAttribute('type', 'button');
      expect(viewElement).toHaveAttribute(
        'aria-label',
        'Click to edit test value'
      );
    });
  });

  describe('edit mode', () => {
    beforeEach(() => {
      mockUseInlineEdit.isEditing = true;
    });

    it('should render input field in edit mode', () => {
      render(<InlineEditField {...defaultProps} />);

      expect(screen.getByRole('textbox')).toBeInTheDocument();
      expect(screen.getByRole('textbox')).toHaveValue('test value');
      expect(screen.queryByText('test value')).not.toBeInTheDocument();
    });

    it('should show save and cancel buttons in edit mode', () => {
      render(<InlineEditField {...defaultProps} />);

      expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /cancel/i })
      ).toBeInTheDocument();
    });

    it('should call setValue when input value changes', async () => {
      render(<InlineEditField {...defaultProps} />);

      const input = screen.getByRole('textbox');
      fireEvent.change(input, { target: { value: 'new value' } });

      expect(mockUseInlineEdit.setValue).toHaveBeenCalledWith('new value');
    });

    it('should call saveEdit when save button is clicked', async () => {
      const user = userEvent.setup();
      render(<InlineEditField {...defaultProps} />);

      const saveButton = screen.getByRole('button', { name: /save/i });
      await user.click(saveButton);

      expect(mockUseInlineEdit.saveEdit).toHaveBeenCalled();
    });

    it('should call cancelEdit when cancel button is clicked', async () => {
      const user = userEvent.setup();
      render(<InlineEditField {...defaultProps} />);

      const cancelButton = screen.getByRole('button', { name: /cancel/i });
      await user.click(cancelButton);

      expect(mockUseInlineEdit.cancelEdit).toHaveBeenCalled();
    });

    it('should call handleKeyDown when key is pressed in input', async () => {
      const user = userEvent.setup();
      render(<InlineEditField {...defaultProps} />);

      const input = screen.getByRole('textbox');
      await user.type(input, '{Enter}');

      expect(mockUseInlineEdit.handleKeyDown).toHaveBeenCalled();
    });

    it('should focus input when entering edit mode', () => {
      render(<InlineEditField {...defaultProps} />);

      const input = screen.getByRole('textbox');
      expect(input).toHaveFocus();
    });

    it('should have proper accessibility attributes in edit mode', () => {
      render(<InlineEditField {...defaultProps} />);

      const input = screen.getByRole('textbox');
      expect(input).toHaveAttribute('aria-label', 'Edit value');
    });
  });

  describe('loading state', () => {
    beforeEach(() => {
      mockUseInlineEdit.isEditing = true;
      mockUseInlineEdit.isLoading = true;
    });

    it('should disable input and buttons when loading', () => {
      render(<InlineEditField {...defaultProps} />);

      expect(screen.getByRole('textbox')).toBeDisabled();
      expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
      expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled();
    });

    it('should show loading state on save button', () => {
      render(<InlineEditField {...defaultProps} />);

      const saveButton = screen.getByRole('button', { name: /save/i });
      expect(saveButton).toBeDisabled();
    });
  });

  describe('error state', () => {
    beforeEach(() => {
      mockUseInlineEdit.isEditing = true;
      mockUseInlineEdit.error = 'Validation error';
    });

    it('should display error message', () => {
      render(<InlineEditField {...defaultProps} />);

      expect(screen.getByText('Validation error')).toBeInTheDocument();
    });

    it('should apply error styling to input', () => {
      render(<InlineEditField {...defaultProps} />);

      const input = screen.getByRole('textbox');
      expect(input).toHaveClass('border-destructive');
    });

    it('should have proper accessibility attributes for error', () => {
      render(<InlineEditField {...defaultProps} />);

      const input = screen.getByRole('textbox');
      const errorMessage = screen.getByText('Validation error');

      expect(input).toHaveAttribute('aria-invalid', 'true');
      expect(input).toHaveAttribute('aria-describedby');
      expect(errorMessage).toHaveAttribute('role', 'alert');
    });
  });

  describe('field types', () => {
    it('should render text input by default', () => {
      mockUseInlineEdit.isEditing = true;
      render(<InlineEditField {...defaultProps} />);

      const input = screen.getByRole('textbox');
      expect(input).toHaveAttribute('type', 'text');
    });

    it('should render email input for email field type', () => {
      mockUseInlineEdit.isEditing = true;
      render(<InlineEditField {...defaultProps} fieldType='email' />);

      const input = screen.getByRole('textbox');
      expect(input).toHaveAttribute('type', 'email');
    });

    it('should render tel input for phone field type', () => {
      mockUseInlineEdit.isEditing = true;
      render(<InlineEditField {...defaultProps} fieldType='phone' />);

      const input = screen.getByRole('textbox');
      expect(input).toHaveAttribute('type', 'tel');
    });
  });

  describe('disabled state', () => {
    it('should not be clickable when disabled', async () => {
      const user = userEvent.setup();
      render(<InlineEditField {...defaultProps} disabled />);

      const viewElement = screen.getByText('test value');
      await user.click(viewElement);

      expect(mockUseInlineEdit.startEdit).not.toHaveBeenCalled();
    });

    it('should have proper styling when disabled', () => {
      render(<InlineEditField {...defaultProps} disabled />);

      const viewElement = screen.getByText('test value');
      expect(viewElement).toHaveClass('opacity-50', 'cursor-not-allowed');
    });
  });

  describe('custom validation', () => {
    it('should pass validation function to useInlineEdit hook', () => {
      const mockValidation = jest.fn();
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { useInlineEdit } = require('@/hooks/useInlineEdit');

      render(<InlineEditField {...defaultProps} validation={mockValidation} />);

      expect(useInlineEdit).toHaveBeenCalledWith(
        'test value',
        expect.any(Function),
        mockValidation,
        expect.any(Object)
      );
    });
  });
});
