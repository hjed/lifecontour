/**
 * Tests for InlineEditEmailField component.
 *
 * Tests the email-specific inline editing component including email validation,
 * proper input type, and integration with the base InlineEditField.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InlineEditEmailField } from '@/components/contacts/InlineEditEmailField';

// Mock the validation functions
jest.mock('@/lib/validation', () => ({
  validateEmail: jest.fn((value: string) => {
    if (!value) return null;
    if (value === 'invalid') return 'Please enter a valid email address';
    if (!value.includes('@')) return 'Please enter a valid email address';
    return null;
  }),
}));

describe('InlineEditEmailField', () => {
  const mockOnSave = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Display and Icon', () => {
    it('renders with email icon by default', () => {
      render(
        <InlineEditEmailField value='test@example.com' onSave={mockOnSave} />
      );

      // SVG icons don't have img role, check for the SVG element
      const emailIcon = screen
        .getByRole('button')
        .closest('div')
        ?.querySelector('svg');
      expect(emailIcon).toBeInTheDocument();
      expect(emailIcon).toHaveClass('lucide-mail');
    });

    it('renders without icon when showIcon is false', () => {
      render(
        <InlineEditEmailField
          value='test@example.com'
          onSave={mockOnSave}
          showIcon={false}
        />
      );

      const emailIcon = screen
        .getByRole('button')
        .closest('div')
        ?.querySelector('svg');
      expect(emailIcon).not.toBeInTheDocument();
    });

    it('displays email address', () => {
      render(
        <InlineEditEmailField value='test@example.com' onSave={mockOnSave} />
      );

      expect(screen.getByText('test@example.com')).toBeInTheDocument();
    });

    it('displays placeholder when value is empty', () => {
      render(
        <InlineEditEmailField
          value=''
          onSave={mockOnSave}
          placeholder='Add email address'
        />
      );

      expect(screen.getByText('Add email address')).toBeInTheDocument();
    });
  });

  describe('Email Validation', () => {
    it('validates email address on save', async () => {
      const user = userEvent.setup();

      render(<InlineEditEmailField value='' onSave={mockOnSave} />);

      // Click to edit
      await user.click(screen.getByRole('button'));

      // Enter invalid email
      const input = screen.getByRole('textbox');
      await user.clear(input);
      await user.type(input, 'invalid');

      // Try to save
      await user.keyboard('{Enter}');

      // Should show validation error
      await waitFor(() => {
        expect(
          screen.getByText('Please enter a valid email address')
        ).toBeInTheDocument();
      });

      // Should not call onSave
      expect(mockOnSave).not.toHaveBeenCalled();
    });

    it('accepts valid email addresses', async () => {
      const user = userEvent.setup();

      render(<InlineEditEmailField value='' onSave={mockOnSave} />);

      // Click to edit
      await user.click(screen.getByRole('button'));

      // Enter valid email
      const input = screen.getByRole('textbox');
      await user.type(input, 'test@example.com');

      // Save
      await user.keyboard('{Enter}');

      await waitFor(() => {
        expect(mockOnSave).toHaveBeenCalledWith('test@example.com');
      });
    });

    it('combines email validation with additional validation', async () => {
      const user = userEvent.setup();
      const additionalValidation = jest.fn((value: string) => {
        if (value === 'blocked@example.com') return 'This email is blocked';
        return null;
      });

      render(
        <InlineEditEmailField
          value=''
          onSave={mockOnSave}
          additionalValidation={additionalValidation}
        />
      );

      // Click to edit
      await user.click(screen.getByRole('button'));

      // Enter email that fails additional validation
      const input = screen.getByRole('textbox');
      await user.type(input, 'blocked@example.com');

      // Try to save
      await user.keyboard('{Enter}');

      // Should show custom validation error
      await waitFor(() => {
        expect(screen.getByText('This email is blocked')).toBeInTheDocument();
      });

      expect(mockOnSave).not.toHaveBeenCalled();
    });
  });

  describe('Accessibility', () => {
    it('has proper ARIA labels', () => {
      render(
        <InlineEditEmailField
          value='test@example.com'
          onSave={mockOnSave}
          aria-label='Work email'
        />
      );

      const button = screen.getByRole('button');
      expect(button).toHaveAttribute('aria-label', 'Work email');
    });

    it('uses default ARIA label when none provided', () => {
      render(
        <InlineEditEmailField value='test@example.com' onSave={mockOnSave} />
      );

      const button = screen.getByRole('button');
      expect(button).toHaveAttribute('aria-label', 'Email address');
    });

    it('has proper input type for email', async () => {
      const user = userEvent.setup();

      render(<InlineEditEmailField value='' onSave={mockOnSave} />);

      // Click to edit
      await user.click(screen.getByRole('button'));

      const input = screen.getByRole('textbox');
      expect(input).toHaveAttribute('type', 'email');
    });
  });

  describe('User Interactions', () => {
    it('enters edit mode on click', async () => {
      const user = userEvent.setup();

      render(
        <InlineEditEmailField value='test@example.com' onSave={mockOnSave} />
      );

      await user.click(screen.getByRole('button'));

      expect(screen.getByRole('textbox')).toBeInTheDocument();
    });

    it('cancels edit on Escape', async () => {
      const user = userEvent.setup();

      render(
        <InlineEditEmailField value='test@example.com' onSave={mockOnSave} />
      );

      // Enter edit mode
      await user.click(screen.getByRole('button'));

      // Press Escape
      await user.keyboard('{Escape}');

      // Should exit edit mode
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
      expect(screen.getByText('test@example.com')).toBeInTheDocument();
    });

    it('saves on Enter key', async () => {
      const user = userEvent.setup();

      render(<InlineEditEmailField value='' onSave={mockOnSave} />);

      // Enter edit mode
      await user.click(screen.getByRole('button'));

      // Type email
      const input = screen.getByRole('textbox');
      await user.type(input, 'new@example.com');

      // Press Enter
      await user.keyboard('{Enter}');

      await waitFor(() => {
        expect(mockOnSave).toHaveBeenCalledWith('new@example.com');
      });
    });
  });

  describe('Custom Props', () => {
    it('applies custom className', () => {
      render(
        <InlineEditEmailField
          value='test@example.com'
          onSave={mockOnSave}
          className='custom-class'
        />
      );

      // The className is applied to the InlineEditField, which is the button
      const button = screen.getByRole('button');
      expect(button).toHaveClass('custom-class');
    });

    it('applies custom data-testid', () => {
      render(
        <InlineEditEmailField
          value='test@example.com'
          onSave={mockOnSave}
          data-testid='email-field'
        />
      );

      expect(screen.getByTestId('email-field')).toBeInTheDocument();
    });

    it('uses custom placeholder', () => {
      render(
        <InlineEditEmailField
          value=''
          onSave={mockOnSave}
          placeholder='Enter work email'
        />
      );

      expect(screen.getByText('Enter work email')).toBeInTheDocument();
    });
  });

  describe('Layout and Styling', () => {
    it('maintains proper layout with icon and field', () => {
      render(
        <InlineEditEmailField value='test@example.com' onSave={mockOnSave} />
      );

      const container = screen.getByRole('button').closest('div');
      expect(container).toHaveClass('inline-flex', 'items-center', 'gap-2');
    });

    it('applies minimum width for better UX', async () => {
      const user = userEvent.setup();

      render(<InlineEditEmailField value='' onSave={mockOnSave} />);

      // Enter edit mode to check container styling
      await user.click(screen.getByRole('button'));

      // Check the outer container div has the min-width class
      const outerContainer = screen
        .getByRole('textbox')
        .closest('div')?.parentElement;
      expect(outerContainer).toHaveClass('min-w-[200px]');
    });
  });
});
