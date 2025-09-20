/**
 * Tests for InlineEditPhoneField component.
 *
 * Tests the phone-specific inline editing component including phone formatting,
 * validation, and integration with the base InlineEditField.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InlineEditPhoneField } from '@/components/contacts/InlineEditPhoneField';

// Mock the validation functions
jest.mock('@/lib/validation', () => ({
  validatePhone: jest.fn((value: string) => {
    if (!value) return null;
    if (value === 'invalid') return 'Please enter a valid phone number';
    return null;
  }),
  formatPhoneNumber: jest.fn((value: string) => {
    if (value === '+61412345678') return '+61 412 345 678';
    if (value === '0412345678') return '(04) 1234 5678';
    return value;
  }),
  formatIncompletePhone: jest.fn((value: string) => {
    if (value === '0412345') return '(04) 1234 5';
    return value;
  }),
}));

describe('InlineEditPhoneField', () => {
  const mockOnSave = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Display and Icon', () => {
    it('renders with phone icon by default', () => {
      render(<InlineEditPhoneField value='+61412345678' onSave={mockOnSave} />);

      // SVG icons don't have img role, check for the SVG element
      const phoneIcon = screen
        .getByRole('button')
        .closest('div')
        ?.querySelector('svg');
      expect(phoneIcon).toBeInTheDocument();
      expect(phoneIcon).toHaveClass('lucide-phone');
    });

    it('renders without icon when showIcon is false', () => {
      render(
        <InlineEditPhoneField
          value='+61412345678'
          onSave={mockOnSave}
          showIcon={false}
        />
      );

      const phoneIcon = screen
        .getByRole('button')
        .closest('div')
        ?.querySelector('svg');
      expect(phoneIcon).not.toBeInTheDocument();
    });

    it('displays formatted phone number', () => {
      render(<InlineEditPhoneField value='+61412345678' onSave={mockOnSave} />);

      expect(screen.getByText('+61 412 345 678')).toBeInTheDocument();
    });

    it('displays placeholder when value is empty', () => {
      render(
        <InlineEditPhoneField
          value=''
          onSave={mockOnSave}
          placeholder='Add phone number'
        />
      );

      expect(screen.getByText('Add phone number')).toBeInTheDocument();
    });
  });

  describe('Phone Validation', () => {
    it('validates phone number on save', async () => {
      const user = userEvent.setup();

      render(<InlineEditPhoneField value='' onSave={mockOnSave} />);

      // Click to edit
      await user.click(screen.getByRole('button'));

      // Enter invalid phone
      const input = screen.getByRole('textbox');
      await user.clear(input);
      await user.type(input, 'invalid');

      // Try to save
      await user.keyboard('{Enter}');

      // Should show validation error
      await waitFor(() => {
        expect(
          screen.getByText('Please enter a valid phone number')
        ).toBeInTheDocument();
      });

      // Should not call onSave
      expect(mockOnSave).not.toHaveBeenCalled();
    });

    it('combines phone validation with additional validation', async () => {
      const user = userEvent.setup();
      const additionalValidation = jest.fn((value: string) => {
        if (value === '+61412345678') return 'Custom error';
        return null;
      });

      render(
        <InlineEditPhoneField
          value=''
          onSave={mockOnSave}
          additionalValidation={additionalValidation}
        />
      );

      // Click to edit
      await user.click(screen.getByRole('button'));

      // Enter valid phone that fails additional validation
      const input = screen.getByRole('textbox');
      await user.type(input, '+61412345678');

      // Try to save
      await user.keyboard('{Enter}');

      // Should show custom validation error
      await waitFor(() => {
        expect(screen.getByText('Custom error')).toBeInTheDocument();
      });

      expect(mockOnSave).not.toHaveBeenCalled();
    });
  });

  describe('Phone Formatting', () => {
    it('formats phone number before saving', async () => {
      const user = userEvent.setup();

      render(<InlineEditPhoneField value='' onSave={mockOnSave} />);

      // Click to edit
      await user.click(screen.getByRole('button'));

      // Enter unformatted phone
      const input = screen.getByRole('textbox');
      await user.type(input, '+61412345678');

      // Save
      await user.keyboard('{Enter}');

      // Should format before saving
      await waitFor(() => {
        expect(mockOnSave).toHaveBeenCalledWith('+61 412 345 678');
      });
    });
  });

  describe('Accessibility', () => {
    it('has proper ARIA labels', () => {
      render(
        <InlineEditPhoneField
          value='+61412345678'
          onSave={mockOnSave}
          aria-label='Mobile phone'
        />
      );

      const button = screen.getByRole('button');
      expect(button).toHaveAttribute('aria-label', 'Mobile phone');
    });

    it('uses default ARIA label when none provided', () => {
      render(<InlineEditPhoneField value='+61412345678' onSave={mockOnSave} />);

      const button = screen.getByRole('button');
      expect(button).toHaveAttribute('aria-label', 'Phone number');
    });

    it('has proper input type for phone', async () => {
      const user = userEvent.setup();

      render(<InlineEditPhoneField value='' onSave={mockOnSave} />);

      // Click to edit
      await user.click(screen.getByRole('button'));

      const input = screen.getByRole('textbox');
      expect(input).toHaveAttribute('type', 'tel');
    });
  });

  describe('User Interactions', () => {
    it('enters edit mode on click', async () => {
      const user = userEvent.setup();

      render(<InlineEditPhoneField value='+61412345678' onSave={mockOnSave} />);

      await user.click(screen.getByRole('button'));

      expect(screen.getByRole('textbox')).toBeInTheDocument();
    });

    it('cancels edit on Escape', async () => {
      const user = userEvent.setup();

      render(<InlineEditPhoneField value='+61412345678' onSave={mockOnSave} />);

      // Enter edit mode
      await user.click(screen.getByRole('button'));

      // Press Escape
      await user.keyboard('{Escape}');

      // Should exit edit mode
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
      expect(screen.getByText('+61 412 345 678')).toBeInTheDocument();
    });

    it('saves on Enter key', async () => {
      const user = userEvent.setup();

      render(<InlineEditPhoneField value='' onSave={mockOnSave} />);

      // Enter edit mode
      await user.click(screen.getByRole('button'));

      // Type phone number
      const input = screen.getByRole('textbox');
      await user.type(input, '0412345678');

      // Press Enter
      await user.keyboard('{Enter}');

      await waitFor(() => {
        expect(mockOnSave).toHaveBeenCalledWith('(04) 1234 5678');
      });
    });
  });

  describe('Custom Props', () => {
    it('applies custom className', () => {
      render(
        <InlineEditPhoneField
          value='+61412345678'
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
        <InlineEditPhoneField
          value='+61412345678'
          onSave={mockOnSave}
          data-testid='phone-field'
        />
      );

      expect(screen.getByTestId('phone-field')).toBeInTheDocument();
    });

    it('uses custom placeholder', () => {
      render(
        <InlineEditPhoneField
          value=''
          onSave={mockOnSave}
          placeholder='Enter mobile number'
        />
      );

      expect(screen.getByText('Enter mobile number')).toBeInTheDocument();
    });
  });
});
