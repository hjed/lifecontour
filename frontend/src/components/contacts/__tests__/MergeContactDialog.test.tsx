import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { contactTestUtils } from '@/test-utils';
import { MergeContactDialog } from '../MergeContactDialog';
import { ContactResource } from '@/types/contacts';

const currentContact = contactTestUtils.createMockContact({
  id: '1',
  attributes: { first_name: 'Current', last_name: 'Person' },
});
// `mock`-prefixed so the jest.mock factory below may reference it lazily.
const mockOtherContact = contactTestUtils.createMockContact({
  id: '2',
  attributes: { first_name: 'Other', last_name: 'Duplicate' },
});

// Capture mutation calls and let individual tests toggle the pending state.
const mutateAsyncMock = jest.fn().mockResolvedValue({ data: { id: '1' } });
const mockMergeState = { isPending: false };
jest.mock('@/lib/api/contacts', () => ({
  useMergeContact: () => ({
    mutateAsync: mutateAsyncMock,
    isPending: mockMergeState.isPending,
  }),
  // The dialog fetches the full source contact once one is chosen.
  useContact: (id: string) => ({
    data: id === '2' ? { data: mockOtherContact } : undefined,
  }),
}));

// Stub the combobox so tests can trigger a selection deterministically and
// assert the current contact is excluded as a merge source.
jest.mock('../ContactSearchCombobox', () => ({
  ContactSearchCombobox: ({
    onSelect,
    excludeContactIds,
  }: {
    onSelect: (c: ContactResource) => void;
    excludeContactIds?: string[];
  }) => (
    <div data-exclude-ids={(excludeContactIds ?? []).join(',')}>
      <button type='button' onClick={() => onSelect(mockOtherContact)}>
        pick-other
      </button>
    </div>
  ),
}));

// Capture the props handed to the resolution dialog and expose hooks to drive
// both a resolve and an overlay/escape-style close.
jest.mock('../MergeContactResolutionDialog', () => ({
  MergeContactResolutionDialog: ({
    survivorContact,
    sourceContact,
    open,
    onOpenChange,
    onResolve,
  }: {
    survivorContact: ContactResource | null;
    sourceContact: ContactResource | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onResolve: (o: Record<string, unknown>) => void;
  }) =>
    open ? (
      <div data-testid='resolution-dialog'>
        <span data-testid='survivor-id'>{survivorContact?.id ?? 'none'}</span>
        <span data-testid='source-id'>{sourceContact?.id ?? 'none'}</span>
        <button
          type='button'
          onClick={() => onResolve({ first_name: 'Other' })}
        >
          resolve-merge
        </button>
        <button type='button' onClick={() => onOpenChange(false)}>
          close-resolution
        </button>
      </div>
    ) : null,
}));

describe('MergeContactDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockMergeState.isPending = false;
  });

  function renderDialog(onMerged = jest.fn()) {
    render(
      <MergeContactDialog
        currentContact={currentContact}
        open={true}
        onOpenChange={jest.fn()}
        onMerged={onMerged}
      />
    );
    return { onMerged };
  }

  it('excludes the current contact from the source search', () => {
    renderDialog();
    const combobox = screen.getByText('pick-other').parentElement;
    expect(combobox).toHaveAttribute('data-exclude-ids', '1');
  });

  it('disables Next until a source contact is selected', async () => {
    const user = userEvent.setup();
    renderDialog();

    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();

    await user.click(screen.getByText('pick-other'));

    expect(screen.getByRole('button', { name: /next/i })).toBeEnabled();
  });

  it('hands off to the resolution dialog with the current contact surviving by default', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByText('pick-other'));
    await user.click(screen.getByRole('button', { name: /next/i }));

    expect(screen.getByTestId('resolution-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('survivor-id')).toHaveTextContent('1');
    expect(screen.getByTestId('source-id')).toHaveTextContent('2');
  });

  it('swaps survivor and source when the survivor toggle is changed', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByText('pick-other'));

    // Choose the other contact as the survivor.
    await user.click(screen.getByTestId('radio-survivor-2'));
    await user.click(screen.getByRole('button', { name: /next/i }));

    expect(screen.getByTestId('survivor-id')).toHaveTextContent('2');
    expect(screen.getByTestId('source-id')).toHaveTextContent('1');
  });

  it('invokes the merge mutation and onMerged with the survivor id', async () => {
    const user = userEvent.setup();
    const { onMerged } = renderDialog();

    await user.click(screen.getByText('pick-other'));
    await user.click(screen.getByRole('button', { name: /next/i }));
    await user.click(screen.getByRole('button', { name: /resolve-merge/i }));

    await waitFor(() => {
      expect(mutateAsyncMock).toHaveBeenCalledWith({
        survivorId: '1',
        sourceId: '2',
        overrides: { first_name: 'Other' },
      });
      expect(onMerged).toHaveBeenCalledWith('1');
    });
  });

  it('does not let an overlay/escape dismiss reopen selection while merging', async () => {
    const user = userEvent.setup();
    mockMergeState.isPending = true;
    renderDialog();

    await user.click(screen.getByText('pick-other'));
    await user.click(screen.getByRole('button', { name: /next/i }));
    expect(screen.getByTestId('resolution-dialog')).toBeInTheDocument();

    // Simulate an overlay/escape close mid-mutation.
    await user.click(screen.getByRole('button', { name: /close-resolution/i }));

    // The resolution dialog stays open and the selection dialog does not reappear.
    expect(screen.getByTestId('resolution-dialog')).toBeInTheDocument();
    expect(screen.queryByText('Merge Another Contact')).not.toBeInTheDocument();
  });
});
