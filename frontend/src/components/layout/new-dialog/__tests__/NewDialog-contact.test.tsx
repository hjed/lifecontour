/**
 * @jest-environment jsdom
 */

import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { NewDialog } from '../NewDialog';
import { useCreateContact } from '@/lib/api/contacts';
import { createMockAppRouter } from '@/test-utils/mock-router';

jest.mock('@/lib/api/contacts', () => ({
  useCreateContact: jest.fn(),
}));

// The Journal panel shares the dialog but is covered by its own tests.
jest.mock('@/components/journals/NewJournalPanel', () => ({
  NewJournalPanel: () => null,
}));

const mockPush = jest.fn();
const mockRouter = { ...createMockAppRouter(), push: mockPush };

jest.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
}));

const mockUseCreateContact = useCreateContact as jest.MockedFunction<
  typeof useCreateContact
>;

describe('NewDialog with the app registry', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('creates a contact from the Contact type and closes', async () => {
    const user = userEvent.setup();
    const mutateAsync = jest.fn().mockResolvedValue({ data: { id: 'c-7' } });
    mockUseCreateContact.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as never);

    render(<NewDialog />);
    await user.click(screen.getByRole('button', { name: 'New' }));
    const dialog = await screen.findByRole('dialog', { name: 'New' });

    const contactType = within(dialog).getByRole('button', {
      name: 'Contact',
    });
    await user.click(contactType);
    expect(contactType).toHaveAttribute('aria-pressed', 'true');

    await user.type(within(dialog).getByLabelText(/first name/i), 'Grace');
    await user.click(
      within(dialog).getByRole('button', { name: /save contact/i })
    );

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/contacts/c-7'));
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ first_name: 'Grace' })
    );
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
  });

  it('does not open the contact when the dialog was closed mid-save', async () => {
    const user = userEvent.setup();
    let resolveCreate: (value: { data: { id: string } }) => void = () => {};
    const mutateAsync = jest.fn(
      () =>
        new Promise(resolve => {
          resolveCreate = resolve;
        })
    );
    mockUseCreateContact.mockReturnValue({
      mutateAsync,
      isPending: false,
    } as never);

    render(<NewDialog />);
    await user.click(screen.getByRole('button', { name: 'New' }));
    const dialog = await screen.findByRole('dialog', { name: 'New' });
    await user.click(within(dialog).getByRole('button', { name: 'Contact' }));
    await user.type(within(dialog).getByLabelText(/first name/i), 'Late');
    await user.click(
      within(dialog).getByRole('button', { name: /save contact/i })
    );
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());

    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
    await act(async () => resolveCreate({ data: { id: 'c-late' } }));

    expect(mockPush).not.toHaveBeenCalled();
  });
});
