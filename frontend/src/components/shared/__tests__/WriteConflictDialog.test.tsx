/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WriteConflictDialog } from '../WriteConflictDialog';
import type { WriteConflict } from '@/lib/write-conflicts';

const reapply = jest.fn<Promise<void>, []>();
const retryRefresh = jest.fn<Promise<void>, []>();
const reset = jest.fn();
let isAuthenticated = true;
const dismiss = jest.fn<void, [number]>();
let conflicts: WriteConflict[] = [];

jest.mock('@/lib/write-conflicts', () => ({
  useWriteConflicts: () => conflicts,
  dismissWriteConflict: (id: number) => dismiss(id),
  resetWriteConflicts: () => reset(),
}));

jest.mock('@/lib/auth/AuthProvider', () => ({
  useAuth: () => ({ state: { isAuthenticated } }),
}));

function conflict(overrides: Partial<WriteConflict> = {}): WriteConflict {
  return {
    id: 7,
    kind: 'contact',
    changed: ['Contact methods', 'Tags'],
    attempted: 'Nickname → Bob',
    refreshed: true,
    reapply,
    retryRefresh,
    ...overrides,
  };
}

describe('WriteConflictDialog', () => {
  beforeEach(() => {
    reapply.mockReset().mockResolvedValue(undefined);
    retryRefresh.mockReset().mockResolvedValue(undefined);
    dismiss.mockReset();
    reset.mockReset();
    isAuthenticated = true;
  });

  it('renders nothing while there is no conflict', () => {
    conflicts = [];
    render(<WriteConflictDialog />);

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('says the record changed elsewhere, what changed, and what the user tried', () => {
    conflicts = [conflict()];
    render(<WriteConflictDialog />);

    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent(
      'This contact was changed on another tab or device'
    );
    expect(screen.getByTestId('write-conflict-changed')).toHaveTextContent(
      'Contact methods, Tags'
    );
    expect(screen.getByTestId('write-conflict-attempted')).toHaveTextContent(
      'Nickname → Bob'
    );
  });

  it('says another part changed when nothing it shows did', () => {
    conflicts = [conflict({ kind: 'journal', changed: [] })];
    render(<WriteConflictDialog />);

    expect(screen.getByTestId('write-conflict-changed')).toHaveTextContent(
      'Another part of this journal changed'
    );
  });

  it('keeps mine by re-applying the write', async () => {
    conflicts = [conflict()];
    render(<WriteConflictDialog />);

    await userEvent.click(screen.getByRole('button', { name: 'Keep mine' }));

    await waitFor(() => expect(reapply).toHaveBeenCalledTimes(1));
  });

  it('stays open and says why when re-applying fails', async () => {
    reapply.mockRejectedValueOnce(new Error('Server unavailable'));
    conflicts = [conflict()];
    render(<WriteConflictDialog />);

    await userEvent.click(screen.getByRole('button', { name: 'Keep mine' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Your change still wasn’t saved: Server unavailable'
    );
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(dismiss).not.toHaveBeenCalled();
  });

  it('offers only to retry when the latest version could not be loaded', async () => {
    conflicts = [conflict({ refreshed: false, changed: [] })];
    render(<WriteConflictDialog />);

    expect(screen.getByRole('alertdialog')).toHaveTextContent(
      'the latest version couldn’t be loaded'
    );
    expect(
      screen.queryByRole('button', { name: 'Keep mine' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Use theirs' })
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));

    expect(retryRefresh).toHaveBeenCalledTimes(1);
  });

  it('shows nothing, and drops the conflicts, once the session has ended', () => {
    isAuthenticated = false;
    conflicts = [conflict()];
    render(<WriteConflictDialog />);

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(reset).toHaveBeenCalled();
  });

  it('cannot be dismissed while Keep mine is saving', async () => {
    // Escape would drop the conflict, and with it the error and retry if the
    // re-applied write then failed.
    reapply.mockReturnValueOnce(new Promise<void>(() => undefined));
    conflicts = [conflict()];
    render(<WriteConflictDialog />);

    await userEvent.click(screen.getByRole('button', { name: 'Keep mine' }));
    await userEvent.keyboard('{Escape}');

    expect(dismiss).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  });

  it('keeps theirs by dismissing the conflict', async () => {
    conflicts = [conflict()];
    render(<WriteConflictDialog />);

    await userEvent.click(screen.getByRole('button', { name: 'Use theirs' }));

    expect(dismiss).toHaveBeenCalledWith(7);
    expect(reapply).not.toHaveBeenCalled();
  });
});
