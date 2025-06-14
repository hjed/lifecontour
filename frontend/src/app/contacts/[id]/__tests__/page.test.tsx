/**
 * @jest-environment jsdom
 */

import { screen, waitFor } from '@testing-library/react';
import ContactDetailPage from '../page';
import {
  useContact,
  useUpdateContact,
  useDeleteContact,
} from '@/lib/api/contacts';
import { ContactResponse } from '@/types/contacts';
import { renderWithProviders, userEvent, contactTestUtils } from '@/test-utils';

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useContact: jest.fn(),
  useUpdateContact: jest.fn(),
  useDeleteContact: jest.fn(),
}));

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useParams: () => ({ id: '1' }),
}));

// Mock date-fns
jest.mock('date-fns', () => ({
  format: jest.fn(() => '1 January 2024'),
}));

jest.mock('date-fns/locale', () => ({
  enAU: {},
}));

// Mock constants
jest.mock('@/lib/constants', () => ({
  DATE_FORMATS: {
    WITH_TIME: 'dd/MM/yyyy HH:mm',
    LONG: 'dd MMMM yyyy',
  },
  VALIDATION_MESSAGES: {
    REQUIRED_FIELD: 'This field is required',
  },
}));

const mockUseContact = useContact as jest.MockedFunction<typeof useContact>;
const mockUseUpdateContact = useUpdateContact as jest.MockedFunction<
  typeof useUpdateContact
>;
const mockUseDeleteContact = useDeleteContact as jest.MockedFunction<
  typeof useDeleteContact
>;

describe('ContactDetailPage', () => {
  beforeEach(() => {
    contactTestUtils.setupContactTest();
  });

  const renderContactDetailPage = () => {
    return renderWithProviders(<ContactDetailPage />);
  };

  const mockContactData: ContactResponse =
    contactTestUtils.createMockContactResponse();

  it('renders loading state', () => {
    mockUseContact.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as any);

    mockUseUpdateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    mockUseDeleteContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderContactDetailPage();

    // Check for skeleton loading components
    const skeletons = screen.getAllByRole('generic');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it('renders error state', () => {
    mockUseContact.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to load contact'),
    } as any);

    mockUseUpdateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    mockUseDeleteContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderContactDetailPage();

    expect(screen.getByText('Failed to load contact')).toBeInTheDocument();
  });

  it('renders contact details', () => {
    mockUseContact.mockReturnValue({
      data: mockContactData,
      isLoading: false,
      error: null,
    } as any);

    mockUseUpdateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    mockUseDeleteContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderContactDetailPage();

    expect(screen.getByText('John Doe')).toBeInTheDocument();
    // Check for nickname text - just check that Johnny appears somewhere
    expect(screen.getByText(/Johnny/)).toBeInTheDocument();
    expect(screen.getByText('john@example.com')).toBeInTheDocument();
  });

  it('handles edit mode toggle', async () => {
    const user = userEvent.setup();

    mockUseContact.mockReturnValue({
      data: mockContactData,
      isLoading: false,
      error: null,
    } as any);

    mockUseUpdateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    mockUseDeleteContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderContactDetailPage();

    const editButton = screen.getByRole('button', { name: /edit/i });
    await user.click(editButton);

    expect(screen.getAllByRole('button', { name: /cancel/i })).toHaveLength(2); // One from edit mode, one from form
    expect(
      screen.getByRole('button', { name: /save contact/i })
    ).toBeInTheDocument();
  });

  it('handles back navigation', async () => {
    const user = userEvent.setup();

    mockUseContact.mockReturnValue({
      data: mockContactData,
      isLoading: false,
      error: null,
    } as any);

    mockUseUpdateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    mockUseDeleteContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderContactDetailPage();

    const backButton = screen.getByRole('button', {
      name: /back to contacts/i,
    });
    await user.click(backButton);

    expect(window.location.href).toBe('/contacts');
  });

  it('handles delete confirmation', async () => {
    const user = userEvent.setup();
    const mockDeleteMutation = jest.fn().mockResolvedValue({});

    mockUseContact.mockReturnValue({
      data: mockContactData,
      isLoading: false,
      error: null,
    } as any);

    mockUseUpdateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    mockUseDeleteContact.mockReturnValue({
      mutateAsync: mockDeleteMutation,
      isPending: false,
    } as any);

    renderContactDetailPage();

    // Find delete button by its accessible label
    const deleteButton = screen.getByRole('button', { name: 'Delete contact' });
    await user.click(deleteButton);

    expect(screen.getByText('Delete Contact')).toBeInTheDocument();
    expect(
      screen.getByText(/are you sure you want to delete/i)
    ).toBeInTheDocument();

    const confirmDeleteButton = screen.getByRole('button', {
      name: /delete$/i,
    });
    await user.click(confirmDeleteButton);

    await waitFor(() => {
      expect(mockDeleteMutation).toHaveBeenCalledWith('1');
    });
  });

  it('handles update contact', async () => {
    const user = userEvent.setup();
    const mockUpdateMutation = jest.fn().mockResolvedValue({});

    mockUseContact.mockReturnValue({
      data: mockContactData,
      isLoading: false,
      error: null,
    } as any);

    mockUseUpdateContact.mockReturnValue({
      mutateAsync: mockUpdateMutation,
      isPending: false,
    } as any);

    mockUseDeleteContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderContactDetailPage();

    // Enter edit mode
    const editButton = screen.getByRole('button', { name: /edit/i });
    await user.click(editButton);

    // Modify the first name
    const firstNameInput = screen.getByDisplayValue('John');
    await user.clear(firstNameInput);
    await user.type(firstNameInput, 'Jane');

    // Save changes
    const saveButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockUpdateMutation).toHaveBeenCalledWith({
        id: '1',
        data: expect.objectContaining({
          first_name: 'Jane',
        }),
      });
    });
  });

  it('displays contact without nickname', () => {
    const contactWithoutNickname = {
      ...mockContactData,
      data: {
        ...mockContactData.data,
        attributes: {
          ...mockContactData.data.attributes,
          nick_name: '',
        },
      },
    };

    mockUseContact.mockReturnValue({
      data: contactWithoutNickname,
      isLoading: false,
      error: null,
    } as any);

    mockUseUpdateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    mockUseDeleteContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as any);

    renderContactDetailPage();

    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.queryByText('"Johnny"')).not.toBeInTheDocument();
  });
});
