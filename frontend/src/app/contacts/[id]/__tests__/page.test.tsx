/**
 * @jest-environment jsdom
 */

import { screen, waitFor } from '@testing-library/react';
import ContactDetailPage from '../page';
import {
  useContact,
  useUpdateContact,
  useDeleteContact,
  useToggleContactFavourite,
} from '@/lib/api/contacts';
import { ContactResponse } from '@/types/contacts';
import {
  renderWithProviders,
  userEvent,
  contactTestUtils,
  setupMocks,
} from '@/test-utils';

// Mock the contacts API hooks
jest.mock('@/lib/api/contacts', () => ({
  useContact: jest.fn(),
  useUpdateContact: jest.fn(),
  useDeleteContact: jest.fn(),
  useToggleContactFavourite: jest.fn(),
}));

// Mock Next.js navigation hooks
jest.mock('next/navigation', () => ({
  useRouter: jest.fn(() => ({
    push: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
  })),
  usePathname: jest.fn(() => '/contacts/1'),
  useSearchParams: jest.fn(() => new URLSearchParams()),
  useParams: jest.fn(() => ({ id: '1' })),
}));

setupMocks.dateFns();

const mockUseContact = useContact as jest.MockedFunction<typeof useContact>;
const mockUseUpdateContact = useUpdateContact as jest.MockedFunction<
  typeof useUpdateContact
>;
const mockUseDeleteContact = useDeleteContact as jest.MockedFunction<
  typeof useDeleteContact
>;
const mockUseToggleContactFavourite =
  useToggleContactFavourite as jest.MockedFunction<
    typeof useToggleContactFavourite
  >;

describe('ContactDetailPage', () => {
  beforeEach(() => {
    contactTestUtils.setupContactTest();
    setupMocks.clearMocks();
    setupMocks.fetch();

    // Mock authenticated session for all tests
    (fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        authenticated: true,
        user: {
          id: '1',
          email: 'test@example.com',
          name: 'Test User',
        },
      }),
    });

    mockUseToggleContactFavourite.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);
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

  it('renders error state', async () => {
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

    // Wait for authentication to complete and error to show
    expect(
      await screen.findByText('Failed to load contact')
    ).toBeInTheDocument();
  });

  it('renders contact details', async () => {
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

    // Wait for authentication to complete and page to load
    expect(await screen.findByText('John Doe')).toBeInTheDocument();
    // Check for nickname text - just check that Johnny appears somewhere
    expect(screen.getByText(/Johnny/)).toBeInTheDocument();
    // Check that the contact information section is rendered
    expect(screen.getByText('Information')).toBeInTheDocument();
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

    // Wait for authentication to complete and page to load
    const editButton = await screen.findByRole('button', { name: /edit/i });
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

    // Wait for authentication to complete and page to load
    const backButton = await screen.findByRole('button', {
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

    // Wait for authentication to complete and page to load
    // Find delete button by its accessible label
    const deleteButton = await screen.findByRole('button', {
      name: 'Delete contact',
    });
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

    // Wait for authentication to complete and page to load
    // Enter edit mode
    const editButton = await screen.findByRole('button', { name: /edit/i });
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

  it('displays contact without nickname', async () => {
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

    // Wait for authentication to complete and page to load
    expect(await screen.findByText('John Doe')).toBeInTheDocument();
    expect(screen.queryByText('"Johnny"')).not.toBeInTheDocument();
  });
});
