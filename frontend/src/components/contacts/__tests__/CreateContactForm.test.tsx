/**
 * @jest-environment jsdom
 */

import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CreateContactForm } from '../CreateContactForm';
import { useCreateContact } from '@/lib/api/contacts';
import { createMockAppRouter } from '@/test-utils/mock-router';

jest.mock('@/lib/api/contacts', () => ({
  useCreateContact: jest.fn(),
}));

const mockPush = jest.fn();
const mockRouter = { ...createMockAppRouter(), push: mockPush };

jest.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
}));

const mockUseCreateContact = useCreateContact as jest.MockedFunction<
  typeof useCreateContact
>;

function mockMutation(mutateAsync: jest.Mock, isPending = false) {
  mockUseCreateContact.mockReturnValue({
    mutateAsync,
    isPending,
  } as never);
}

describe('CreateContactForm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('creates the contact, reports it, then opens its page', async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    const mutateAsync = jest.fn().mockImplementation(async () => {
      calls.push('create');
      return { data: { id: 'c-42' } };
    });
    const onCreated = jest.fn(() => calls.push('created'));
    mockPush.mockImplementation(() => calls.push('push'));
    mockMutation(mutateAsync);

    render(<CreateContactForm onCancel={jest.fn()} onCreated={onCreated} />);

    await user.type(screen.getByLabelText(/first name/i), 'Ada');
    await user.click(screen.getByRole('button', { name: /save contact/i }));

    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith('/contacts/c-42')
    );
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ first_name: 'Ada' })
    );
    expect(calls).toEqual(['create', 'created', 'push']);
  });

  it('stays put when the create fails', async () => {
    const user = userEvent.setup();
    const consoleSpy = jest
      .spyOn(console, 'error')
      .mockImplementation(() => {});
    const mutateAsync = jest.fn().mockRejectedValue(new Error('nope'));
    const onCreated = jest.fn();
    mockMutation(mutateAsync);

    render(<CreateContactForm onCancel={jest.fn()} onCreated={onCreated} />);

    await user.type(screen.getByLabelText(/first name/i), 'Ada');
    await user.click(screen.getByRole('button', { name: /save contact/i }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(onCreated).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/first name/i)).toHaveValue('Ada');
    consoleSpy.mockRestore();
  });

  it('calls onCancel from Cancel', async () => {
    const user = userEvent.setup();
    const onCancel = jest.fn();
    mockMutation(jest.fn());

    render(<CreateContactForm onCancel={onCancel} />);

    await user.click(screen.getByRole('button', { name: /cancel/i }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('disables Save while the create is pending', () => {
    mockMutation(jest.fn(), true);

    render(<CreateContactForm onCancel={jest.fn()} />);

    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled();
  });

  it('neither reports nor navigates when unmounted before the create settles', async () => {
    const user = userEvent.setup();
    let resolveCreate: (value: { data: { id: string } }) => void = () => {};
    const mutateAsync = jest.fn(
      () =>
        new Promise(resolve => {
          resolveCreate = resolve;
        })
    );
    const onCreated = jest.fn();
    mockMutation(mutateAsync);

    const { unmount } = render(
      <CreateContactForm onCancel={jest.fn()} onCreated={onCreated} />
    );
    await user.type(screen.getByLabelText(/first name/i), 'Ada');
    await user.click(screen.getByRole('button', { name: /save contact/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());

    unmount();
    await act(async () => resolveCreate({ data: { id: 'c-late' } }));

    expect(onCreated).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
  });
});
