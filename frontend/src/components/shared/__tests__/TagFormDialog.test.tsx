/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import {
  TagFormDialog,
  type TagFormLimits,
  type TagFormOption,
  type TagFormValues,
} from '../TagFormDialog';

const PARENT_OPTIONS: TagFormOption[] = [
  { id: '10', name: 'Outdoors' },
  { id: '20', name: 'Indoors' },
];

const INITIAL: TagFormValues = {
  name: 'Climbing',
  color: '#38a169',
  description: 'Rock climbing entries',
  parentId: '10',
};

interface RenderOptions {
  readonly initialValues?: TagFormValues;
  readonly parentOptions?: readonly TagFormOption[];
  readonly isSubmitting?: boolean;
  readonly open?: boolean;
  readonly limits?: TagFormLimits;
  readonly onSubmit?: jest.Mock;
  readonly onOpenChange?: jest.Mock;
  readonly onDelete?: jest.Mock;
  readonly onMerge?: jest.Mock;
  readonly mergeOptions?: readonly TagFormOption[];
}

function renderDialog(options: RenderOptions = {}) {
  const onSubmit = options.onSubmit ?? jest.fn().mockResolvedValue(undefined);
  const onOpenChange = options.onOpenChange ?? jest.fn();

  const element = (overrides: RenderOptions = {}) => {
    const merged = { ...options, ...overrides };
    return (
      <TagFormDialog
        open={merged.open ?? true}
        onOpenChange={onOpenChange}
        title='Edit Tag'
        description='Make changes to your tag here.'
        submitLabel='Save Changes'
        submittingLabel='Saving...'
        initialValues={merged.initialValues ?? INITIAL}
        parentOptions={
          'parentOptions' in merged ? merged.parentOptions : PARENT_OPTIONS
        }
        onSubmit={onSubmit}
        isSubmitting={merged.isSubmitting ?? false}
        limits={merged.limits ?? { name: 50, description: 255 }}
        entityNounPlural='journals'
        {...(merged.onDelete ? { onDelete: merged.onDelete } : {})}
        {...(merged.onMerge ? { onMerge: merged.onMerge } : {})}
        {...(merged.mergeOptions ? { mergeOptions: merged.mergeOptions } : {})}
      />
    );
  };

  const { rerender } = render(element());

  return {
    onSubmit,
    onOpenChange,
    rerenderWith: (overrides: RenderOptions) => rerender(element(overrides)),
  };
}

/** Radix Select needs the trigger opened before its options exist in the DOM. */
async function chooseOption(
  user: ReturnType<typeof userEvent.setup>,
  triggerLabel: string,
  optionName: string
): Promise<void> {
  await user.click(screen.getByLabelText(triggerLabel));
  await user.click(await screen.findByRole('option', { name: optionName }));
}

describe('TagFormDialog', () => {
  it('exposes the title as the dialog accessible name', () => {
    renderDialog();

    expect(
      screen.getByRole('dialog', { name: 'Edit Tag' })
    ).toBeInTheDocument();
  });

  it('pre-populates every field from initialValues', () => {
    renderDialog();

    expect(screen.getByLabelText(/^Name/i)).toHaveValue('Climbing');
    expect(screen.getByLabelText(/Description/i)).toHaveValue(
      'Rock climbing entries'
    );
    expect(screen.getByPlaceholderText('#000000')).toHaveValue('#38a169');
    expect(screen.getByLabelText('Parent Tag')).toHaveTextContent('Outdoors');
  });

  it('requires a name', async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog();

    await user.clear(screen.getByLabelText(/^Name/i));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    expect(await screen.findByText('Name is required')).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('rejects a name longer than 50 characters', async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog();

    const nameInput = screen.getByLabelText(/^Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'x'.repeat(51));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(onSubmit).not.toHaveBeenCalled();
    });
    expect(screen.getByText(/no more than 50 characters/i)).toBeInTheDocument();
  });

  it('honours a namespace name limit above the default', async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog({ limits: { name: 100 } });

    const eighty = 'x'.repeat(80);
    const nameInput = screen.getByLabelText(/^Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, eighty);
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ name: eighty })
      );
    });
  });

  it('accepts any description length when the namespace sets no limit', async () => {
    const user = userEvent.setup();
    const longDescription = 'y'.repeat(400);
    const { onSubmit } = renderDialog({
      limits: { name: 100 },
      initialValues: { ...INITIAL, description: longDescription },
    });

    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ description: longDescription })
      );
    });
  });

  it('rejects a colour that is not a 6-digit hex value', async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog();

    const colorInput = screen.getByPlaceholderText('#000000');
    await user.clear(colorInput);
    await user.type(colorInput, 'green');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    expect(
      await screen.findByText(/hex colour, for example #38A169/i)
    ).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('keeps the hex field in step with the colour picker', async () => {
    const user = userEvent.setup();
    renderDialog();

    const picker = screen.getByLabelText('Color Picker');
    await user.clear(screen.getByPlaceholderText('#000000'));
    await user.type(screen.getByPlaceholderText('#000000'), '#3182ce');

    expect(picker).toHaveValue('#3182ce');
  });

  it('submits the normalised values including the chosen parent', async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog();

    await chooseOption(user, 'Parent Tag', 'Indoors');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        name: 'Climbing',
        color: '#38a169',
        description: 'Rock climbing entries',
        parentId: '20',
      });
    });
  });

  it('submits a null parent when the root option is chosen', async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog();

    await chooseOption(user, 'Parent Tag', 'None (Root Level)');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ parentId: null })
      );
    });
  });

  it('omits the parent field entirely when no parent options are supplied', () => {
    renderDialog({ parentOptions: undefined });

    expect(screen.queryByLabelText('Parent Tag')).not.toBeInTheDocument();
  });

  it('shows the submitting label and disables the submit button while pending', () => {
    renderDialog({ isSubmitting: true });

    const submit = screen.getByRole('button', { name: 'Saving...' });
    expect(submit).toBeDisabled();
  });

  it('closes without submitting when cancelled', async () => {
    const user = userEvent.setup();
    const { onSubmit, onOpenChange } = renderDialog();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('discards an abandoned draft when reopened', async () => {
    // The dialog stays mounted between openings (the context menu keeps it
    // alive), so a half-typed name must not survive a close.
    const user = userEvent.setup();
    const { rerenderWith } = renderDialog();

    await user.clear(screen.getByLabelText(/^Name/i));
    await user.type(screen.getByLabelText(/^Name/i), 'Half typed');

    rerenderWith({ open: false });
    rerenderWith({ open: true });

    expect(screen.getByLabelText(/^Name/i)).toHaveValue('Climbing');
  });

  it('re-seeds the form when the subject tag changes', () => {
    const { rerenderWith } = renderDialog();

    expect(screen.getByLabelText(/^Name/i)).toHaveValue('Climbing');

    rerenderWith({
      initialValues: {
        name: 'Cooking',
        color: '#d69e2e',
        description: 'Kitchen entries',
        parentId: null,
      },
    });

    expect(screen.getByLabelText(/^Name/i)).toHaveValue('Cooking');
    expect(screen.getByLabelText(/Description/i)).toHaveValue(
      'Kitchen entries'
    );
    expect(screen.getByLabelText('Parent Tag')).toHaveTextContent(
      'None (Root Level)'
    );
  });

  it('does not carry a chosen merge target across a close', async () => {
    // Closing by any route must clear the merge target: a stale one leaves the
    // Merge button live on the next open, pointing at a tag the user picked in
    // an earlier session of the dialog.
    const user = userEvent.setup();
    const onMerge = jest.fn().mockResolvedValue(undefined);
    const { rerenderWith } = renderDialog({
      onMerge,
      mergeOptions: PARENT_OPTIONS,
    });

    await user.click(screen.getByLabelText('Merge into'));
    await user.click(await screen.findByRole('option', { name: 'Indoors' }));
    expect(screen.getByRole('button', { name: 'Merge' })).toBeEnabled();

    // Close via Save Changes rather than Cancel — this is the path that used to
    // skip the reset.
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    rerenderWith({ open: false });
    rerenderWith({ open: true });

    expect(screen.getByRole('button', { name: 'Merge' })).toBeDisabled();
    expect(onMerge).not.toHaveBeenCalled();
  });

  // The parent select has its own value space, so no tag id can shadow the "no
  // parent" option however arbitrary the id is. Both plausible sentinel spellings
  // are covered so the guarantee does not quietly depend on which one is used.
  it.each(['none', 'root'])(
    'keeps a tag whose id is %p selectable as a parent',
    async id => {
      const user = userEvent.setup();
      const { onSubmit } = renderDialog({
        parentOptions: [{ id, name: 'Sentinel Lookalike' }],
        initialValues: { ...INITIAL, parentId: null },
      });

      await chooseOption(user, 'Parent Tag', 'Sentinel Lookalike');
      await user.click(screen.getByRole('button', { name: 'Save Changes' }));

      await waitFor(() => {
        expect(onSubmit).toHaveBeenCalledWith(
          expect.objectContaining({ parentId: id })
        );
      });
    }
  );

  it('renders no delete or merge affordances when their callbacks are absent', () => {
    renderDialog();

    expect(
      screen.queryByRole('button', { name: /delete tag/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /^merge$/i })
    ).not.toBeInTheDocument();
  });

  it('confirms before deleting when onDelete is supplied', async () => {
    const user = userEvent.setup();
    const onDelete = jest.fn().mockResolvedValue(undefined);
    renderDialog({ onDelete });

    await user.click(screen.getByRole('button', { name: 'Delete Tag' }));

    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(
      screen.getByText(/remove it from all journals/i)
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(onDelete).toHaveBeenCalledTimes(1);
    });
  });

  it('merges into the selected target after confirmation when onMerge is supplied', async () => {
    const user = userEvent.setup();
    const onMerge = jest.fn().mockResolvedValue(undefined);
    renderDialog({ onMerge, mergeOptions: PARENT_OPTIONS });

    const mergeButton = screen.getByRole('button', { name: 'Merge' });
    expect(mergeButton).toBeDisabled();

    await user.click(screen.getByLabelText('Merge into'));
    await user.click(await screen.findByRole('option', { name: 'Indoors' }));
    await user.click(screen.getByRole('button', { name: 'Merge' }));

    await user.click(screen.getByRole('button', { name: 'Confirm Merge' }));

    await waitFor(() => {
      expect(onMerge).toHaveBeenCalledWith('20');
    });
  });
});
