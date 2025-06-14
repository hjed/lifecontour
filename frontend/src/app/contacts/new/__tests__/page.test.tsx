/**
 * @jest-environment jsdom
 */

import { screen, waitFor } from '@testing-library/react';
import NewContactPage from '../page';
import { useCreateContact } from '@/lib/api/contacts';
import { renderWithProviders, userEvent, contactTestUtils } from '@/test-utils';

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useCreateContact: jest.fn(),
}));

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
  }),
}));

// Mock constants
jest.mock('@/lib/constants', () => ({
  VALIDATION_MESSAGES: {
    REQUIRED_FIELD: 'This field is required',
  },
}));

const mockUseCreateContact = useCreateContact as jest.MockedFunction<
  typeof useCreateContact
>;

describe('NewContactPage', () => {
  beforeEach(() => {
    contactTestUtils.setupContactTest();
  });

  const renderNewContactPage = () => {
    return renderWithProviders(<NewContactPage />);
  };

  it('renders the new contact page', () => {
    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderNewContactPage();

    expect(screen.getByText('Add New Contact')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Create a new contact with their information and details'
      )
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /back to contacts/i })
    ).toBeInTheDocument();
  });

  it('renders the contact form', () => {
    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderNewContactPage();

    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/last name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/middle name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/nickname/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /save contact/i })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('handles back navigation', async () => {
    const user = userEvent.setup();

    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderNewContactPage();

    const backButton = screen.getByRole('button', {
      name: /back to contacts/i,
    });
    await user.click(backButton);

    expect(window.location.href).toBe('/contacts');
  });

  it('handles cancel navigation', async () => {
    const user = userEvent.setup();

    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderNewContactPage();

    const cancelButton = screen.getByRole('button', { name: /cancel/i });
    await user.click(cancelButton);

    expect(window.location.href).toBe('/contacts');
  });

  it('handles form submission', async () => {
    const user = userEvent.setup();
    const mockCreateMutation = jest.fn().mockResolvedValue({
      data: { id: '123' },
    });

    mockUseCreateContact.mockReturnValue({
      mutateAsync: mockCreateMutation,
      isPending: false,
    } as any);

    renderNewContactPage();

    // Fill in the form
    const firstNameInput = screen.getByLabelText(/first name/i);
    const lastNameInput = screen.getByLabelText(/last name/i);

    await user.type(firstNameInput, 'John');
    await user.type(lastNameInput, 'Doe');

    // Submit the form
    const saveButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockCreateMutation).toHaveBeenCalledWith({
        first_name: 'John',
        last_name: 'Doe',
        middle_name: '',
        nick_name: '',
        contact_methods: [],
        addresses: [],
        notes: [],
      });
    });

    // Should navigate to the created contact
    expect(window.location.href).toBe('/contacts/123');
  });

  it('handles form submission with all fields', async () => {
    const user = userEvent.setup();
    const mockCreateMutation = jest.fn().mockResolvedValue({
      data: { id: '456' },
    });

    mockUseCreateContact.mockReturnValue({
      mutateAsync: mockCreateMutation,
      isPending: false,
    } as any);

    renderNewContactPage();

    // Fill in all form fields
    await user.type(screen.getByLabelText(/first name/i), 'Jane');
    await user.type(screen.getByLabelText(/last name/i), 'Smith');
    await user.type(screen.getByLabelText(/middle name/i), 'Marie');
    await user.type(screen.getByLabelText(/nickname/i), 'Janie');

    // Submit the form
    const saveButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockCreateMutation).toHaveBeenCalledWith({
        first_name: 'Jane',
        last_name: 'Smith',
        middle_name: 'Marie',
        nick_name: 'Janie',
        contact_methods: [],
        addresses: [],
        notes: [],
      });
    });

    expect(window.location.href).toBe('/contacts/456');
  });

  it('handles form submission error', async () => {
    const user = userEvent.setup();
    const mockCreateMutation = jest
      .fn()
      .mockRejectedValue(new Error('Creation failed'));

    // Suppress console.error for this test since we expect an error
    const consoleSpy = jest
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    mockUseCreateContact.mockReturnValue({
      mutateAsync: mockCreateMutation,
      isPending: false,
    } as any);

    renderNewContactPage();

    // Fill in the form
    await user.type(screen.getByLabelText(/first name/i), 'John');

    // Submit the form
    const saveButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockCreateMutation).toHaveBeenCalled();
    });

    // Form should still be visible after error
    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();

    // Restore console.error
    consoleSpy.mockRestore();
  });

  it('shows loading state during submission', () => {
    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: true,
    } as any);

    renderNewContactPage();

    expect(screen.getByRole('button', { name: /saving/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled();
  });

  it('validates required fields', async () => {
    const user = userEvent.setup();

    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderNewContactPage();

    // Try to submit without filling required fields
    const saveButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(saveButton);

    // Should show validation error
    await waitFor(() => {
      expect(screen.getByText(/this field is required/i)).toBeInTheDocument();
    });
  });
});
