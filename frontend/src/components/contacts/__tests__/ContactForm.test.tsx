/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContactForm } from '../ContactForm';
import { ContactFormData } from '@/types/contacts';

// Mock the constants
jest.mock('@/lib/constants', () => ({
  VALIDATION_MESSAGES: {
    REQUIRED_FIELD: 'This field is required',
  },
}));

describe('ContactForm', () => {
  const mockOnSubmit = jest.fn();
  const mockOnCancel = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  const defaultProps = {
    onSubmit: mockOnSubmit,
    onCancel: mockOnCancel,
    isLoading: false,
  };

  it('renders the form with basic fields', () => {
    render(<ContactForm {...defaultProps} />);

    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/last name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/middle name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/nickname/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /save contact/i })
    ).toBeInTheDocument();
  });

  it('shows cancel button when onCancel is provided', () => {
    render(<ContactForm {...defaultProps} />);
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('does not show cancel button when onCancel is not provided', () => {
    render(<ContactForm onSubmit={mockOnSubmit} isLoading={false} />);
    expect(
      screen.queryByRole('button', { name: /cancel/i })
    ).not.toBeInTheDocument();
  });

  it('populates form with initial data', () => {
    const initialData: ContactFormData = {
      first_name: 'John',
      last_name: 'Doe',
      middle_name: 'William',
      nick_name: 'Johnny',
      contact_methods: [],
      addresses: [],
      notes: [],
    };

    render(<ContactForm {...defaultProps} initialData={initialData} />);

    expect(screen.getByDisplayValue('John')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Doe')).toBeInTheDocument();
    expect(screen.getByDisplayValue('William')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Johnny')).toBeInTheDocument();
  });

  it('validates required fields', async () => {
    const user = userEvent.setup();
    render(<ContactForm {...defaultProps} />);

    const submitButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/this field is required/i)).toBeInTheDocument();
    });

    expect(mockOnSubmit).not.toHaveBeenCalled();
  });

  it('submits form with valid data', async () => {
    const user = userEvent.setup();
    render(<ContactForm {...defaultProps} />);

    const firstNameInput = screen.getByLabelText(/first name/i);
    const lastNameInput = screen.getByLabelText(/last name/i);
    const submitButton = screen.getByRole('button', { name: /save contact/i });

    await user.type(firstNameInput, 'John');
    await user.type(lastNameInput, 'Doe');
    await user.click(submitButton);

    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith({
        first_name: 'John',
        last_name: 'Doe',
        middle_name: '',
        nick_name: '',
        contact_methods: [],
        addresses: [],
        notes: [],
      });
    });
  });

  it('calls onCancel when cancel button is clicked', async () => {
    const user = userEvent.setup();
    render(<ContactForm {...defaultProps} />);

    const cancelButton = screen.getByRole('button', { name: /cancel/i });
    await user.click(cancelButton);

    expect(mockOnCancel).toHaveBeenCalled();
  });

  it('disables form when loading', () => {
    render(<ContactForm {...defaultProps} isLoading={true} />);

    const submitButton = screen.getByRole('button', { name: /saving/i });
    const cancelButton = screen.getByRole('button', { name: /cancel/i });

    expect(submitButton).toBeDisabled();
    expect(cancelButton).toBeDisabled();
  });

  it('shows loading state on submit button', () => {
    render(<ContactForm {...defaultProps} isLoading={true} />);

    expect(screen.getByRole('button', { name: /saving/i })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /save contact/i })
    ).not.toBeInTheDocument();
  });

  it('handles form submission errors gracefully', async () => {
    const user = userEvent.setup();
    const mockOnSubmitWithError = jest
      .fn()
      .mockRejectedValue(new Error('Submission failed'));

    // Suppress console.error for this test since we expect an error
    const consoleSpy = jest
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    render(<ContactForm {...defaultProps} onSubmit={mockOnSubmitWithError} />);

    const firstNameInput = screen.getByLabelText(/first name/i);
    const submitButton = screen.getByRole('button', { name: /save contact/i });

    await user.type(firstNameInput, 'John');
    await user.click(submitButton);

    await waitFor(() => {
      expect(mockOnSubmitWithError).toHaveBeenCalled();
    });

    // Form should still be functional after error
    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();

    // Restore console.error
    consoleSpy.mockRestore();
  });

  it('allows editing all form fields', async () => {
    const user = userEvent.setup();
    render(<ContactForm {...defaultProps} />);

    const firstNameInput = screen.getByLabelText(/first name/i);
    const lastNameInput = screen.getByLabelText(/last name/i);
    const middleNameInput = screen.getByLabelText(/middle name/i);
    const nickNameInput = screen.getByLabelText(/nickname/i);

    await user.type(firstNameInput, 'Jane');
    await user.type(lastNameInput, 'Smith');
    await user.type(middleNameInput, 'Marie');
    await user.type(nickNameInput, 'Janie');

    expect(firstNameInput).toHaveValue('Jane');
    expect(lastNameInput).toHaveValue('Smith');
    expect(middleNameInput).toHaveValue('Marie');
    expect(nickNameInput).toHaveValue('Janie');
  });

  it('has proper accessibility attributes', async () => {
    const user = userEvent.setup();
    render(<ContactForm {...defaultProps} />);

    // Test that form fields have proper labels
    const firstNameInput = screen.getByLabelText(/first name/i);
    expect(firstNameInput).toHaveAttribute('id');

    // Test that error messages are properly linked
    const submitButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(submitButton);

    await waitFor(() => {
      const errorMessage = screen.getByText(/this field is required/i);
      expect(errorMessage).toBeInTheDocument();

      // Check that the input has aria-invalid when there's an error
      expect(firstNameInput).toHaveAttribute('aria-invalid', 'true');

      // Check that the input is described by the error message
      const ariaDescribedBy = firstNameInput.getAttribute('aria-describedby');
      expect(ariaDescribedBy).toBeTruthy();

      // The error message should have an ID that matches the aria-describedby
      const errorId = errorMessage.getAttribute('id');
      expect(ariaDescribedBy).toContain(errorId);
    });
  });

  it('preserves existing contact methods, addresses, and notes when editing', async () => {
    const user = userEvent.setup();

    // Mock existing contact data with contact methods, addresses, and notes
    const initialData: ContactFormData = {
      first_name: 'John',
      last_name: 'Doe',
      middle_name: 'William',
      nick_name: 'Johnny',
      contact_methods: [
        {
          type: 'contact_methods',
          id: '1',
          attributes: {
            method_type: 'email' as any,
            value: 'john@example.com',
            label: 'Work',
            is_primary: true,
          },
        },
      ],
      addresses: [
        {
          type: 'contact_addresses',
          id: '1',
          attributes: {
            label: 'Home',
            street_line_1: '123 Main St',
            locality: 'Anytown',
            region: 'CA',
            postal_code: '12345',
            country_code: 'US',
            is_primary: true,
          },
        },
      ],
      notes: [
        {
          type: 'contact_notes',
          id: '1',
          attributes: {
            content: 'Important client contact',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        },
      ],
    };

    render(<ContactForm {...defaultProps} initialData={initialData} />);

    // Update the first name
    const firstNameInput = screen.getByLabelText(/first name/i);
    await user.clear(firstNameInput);
    await user.type(firstNameInput, 'Jane');

    const submitButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith({
        first_name: 'Jane',
        last_name: 'Doe',
        middle_name: 'William',
        nick_name: 'Johnny',
        // These should be preserved from initialData
        contact_methods: initialData.contact_methods,
        addresses: initialData.addresses,
        notes: initialData.notes,
      });
    });
  });

  it('uses empty arrays for contact methods, addresses, and notes when creating new contact', async () => {
    const user = userEvent.setup();

    // No initialData provided (new contact scenario)
    render(<ContactForm {...defaultProps} />);

    const firstNameInput = screen.getByLabelText(/first name/i);
    const submitButton = screen.getByRole('button', { name: /save contact/i });

    await user.type(firstNameInput, 'New');
    await user.click(submitButton);

    await waitFor(() => {
      expect(mockOnSubmit).toHaveBeenCalledWith({
        first_name: 'New',
        last_name: '',
        middle_name: '',
        nick_name: '',
        // These should be empty arrays for new contacts
        contact_methods: [],
        addresses: [],
        notes: [],
      });
    });
  });
});
