import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MergeContactDialog } from '../MergeContactDialog';
import { ContactResource } from '@/types/contacts';

function buildContact(
  id: string,
  attrs: Partial<ContactResource['attributes']>
): ContactResource {
  return {
    id,
    type: 'contacts',
    attributes: {
      first_name: '',
      last_name: '',
      middle_name: '',
      nick_name: '',
      photo_url: null,
      is_favourite: false,
      created_at: '',
      updated_at: '',
      contact_methods: [],
      addresses: [],
      notes: [],
      relationships: [],
      important_dates: [],
      summary: null,
      ...attrs,
    },
  } as ContactResource;
}

const currentContact = buildContact('1', {
  first_name: 'Current',
  last_name: 'Person',
});
const otherContact = buildContact('2', {
  first_name: 'Other',
  last_name: 'Duplicate',
});

// Capture mutation calls
const mutateAsyncMock = jest.fn().mockResolvedValue({ data: { id: '1' } });
jest.mock('@/lib/api/contacts', () => ({
  useMergeContact: () => ({
    mutateAsync: mutateAsyncMock,
    isPending: false,
  }),
  // The dialog fetches the full source contact once one is chosen.
  useContact: (id: string) => ({
    data: id === '2' ? { data: otherContact } : undefined,
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
      <button type='button' onClick={() => onSelect(otherContact)}>
        pick-other
      </button>
    </div>
  ),
}));

// Capture the props handed to the resolution dialog.
jest.mock('../MergeContactResolutionDialog', () => ({
  MergeContactResolutionDialog: ({
    survivorContact,
    sourceContact,
    open,
    onResolve,
  }: {
    survivorContact: ContactResource | null;
    sourceContact: ContactResource | null;
    open: boolean;
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
      </div>
    ) : null,
}));

describe('MergeContactDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
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
});
