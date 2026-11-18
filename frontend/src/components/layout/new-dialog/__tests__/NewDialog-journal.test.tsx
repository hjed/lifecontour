/**
 * @jest-environment jsdom
 */

import type { ReactElement } from 'react';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { NewDialog } from '../NewDialog';
import { createMockAppRouter } from '@/test-utils/mock-router';

const mockCreateJournal = jest.fn();
jest.mock('@/lib/api/journals', () => ({
  useCreateJournal: () => ({
    mutateAsync: mockCreateJournal,
    isPending: false,
  }),
  useJournal: () => ({ data: undefined, isLoading: false, error: null }),
}));

jest.mock('@/lib/api/routes', () => ({
  useCreateRoute: () => ({ mutateAsync: jest.fn(), isPending: false }),
}));

jest.mock('@/lib/api/settings', () => ({
  ...jest.requireActual('@/lib/api/settings'),
  useUserTimezone: () => 'Australia/Sydney',
}));

jest.mock('@/lib/api/contacts', () => ({
  useCreateContact: () => ({ mutateAsync: jest.fn(), isPending: false }),
}));

const mockPush = jest.fn();
const mockRouter = { ...createMockAppRouter(), push: mockPush };

jest.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
}));

function renderDialog(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>
  );
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'New' }));
  return screen.findByRole('dialog', { name: 'New' });
}

function typeButton(dialog: HTMLElement, name: string) {
  return within(
    within(dialog).getByRole('group', { name: 'What to create' })
  ).getByRole('button', { name });
}

describe('NewDialog with the app registry: Journal', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('opens on Journal, holding the journal create form', async () => {
    const user = userEvent.setup();
    renderDialog(<NewDialog />);

    const dialog = await openDialog(user);

    expect(typeButton(dialog, 'Journal')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    const panel = within(dialog).getByRole('region', { name: 'Journal' });
    expect(within(panel).getByLabelText(/^title$/i)).toBeInTheDocument();
    expect(
      within(panel).getByRole('button', { name: /create journal/i })
    ).toBeInTheDocument();
  });

  it('creates a journal, closes, and opens the new journal', async () => {
    const user = userEvent.setup();
    mockCreateJournal.mockResolvedValue({ data: { id: 'j-1' } });
    renderDialog(<NewDialog />);
    const dialog = await openDialog(user);
    const panel = within(dialog).getByRole('region', { name: 'Journal' });

    await user.type(within(panel).getByLabelText(/^title$/i), 'Hut trip');
    await user.click(
      within(panel).getByRole('button', { name: /create journal/i })
    );

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/journals/j-1'));
    expect(mockCreateJournal).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Hut trip' })
    );
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
  });

  it('keeps what was typed in each type when switching between them', async () => {
    const user = userEvent.setup();
    renderDialog(<NewDialog />);
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText(/^title$/i), 'Kept title');
    await user.click(typeButton(dialog, 'Contact'));
    await user.type(within(dialog).getByLabelText(/first name/i), 'Ada');
    await user.click(typeButton(dialog, 'Journal'));

    expect(within(dialog).getByLabelText(/^title$/i)).toHaveValue('Kept title');

    await user.click(typeButton(dialog, 'Contact'));
    expect(within(dialog).getByLabelText(/first name/i)).toHaveValue('Ada');
  });

  it('does not open the journal when the dialog was closed mid-save', async () => {
    const user = userEvent.setup();
    let resolveCreate: (value: { data: { id: string } }) => void = () => {};
    mockCreateJournal.mockImplementation(
      () =>
        new Promise(resolve => {
          resolveCreate = resolve;
        })
    );
    renderDialog(<NewDialog />);
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText(/^title$/i), 'Late');
    await user.click(
      within(dialog).getByRole('button', { name: /create journal/i })
    );
    await waitFor(() => expect(mockCreateJournal).toHaveBeenCalled());

    await user.keyboard('{Escape}');
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
    await act(async () => resolveCreate({ data: { id: 'j-late' } }));

    expect(mockPush).not.toHaveBeenCalled();
  });

  it('closes from the Journal panel Cancel without creating or navigating', async () => {
    const user = userEvent.setup();
    renderDialog(<NewDialog />);
    const dialog = await openDialog(user);
    const panel = within(dialog).getByRole('region', { name: 'Journal' });

    await user.click(within(panel).getByRole('button', { name: 'Cancel' }));

    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
    expect(mockCreateJournal).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
  });
});
