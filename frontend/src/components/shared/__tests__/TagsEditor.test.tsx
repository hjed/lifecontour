/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { TagsEditor, type TagView } from '../TagsEditor';

const COLORS = ['#E53E3E', '#DD6B20', '#D69E2E', '#38A169'] as const;

const assignedTags: TagView[] = [
  { id: '1', name: 'Work', color: '#3182CE' },
  { id: '2', name: 'Family', color: '#38A169' },
];

const allTags: TagView[] = [
  ...assignedTags,
  { id: '3', name: 'Friends', color: '#D53F8C' },
  { id: '4', name: 'Business', color: '#805AD5', parentId: '1' }, // child of Work
];

interface RenderOptions {
  readonly assigned?: TagView[];
  readonly all?: TagView[];
  readonly isLoading?: boolean;
  readonly isError?: boolean;
  readonly isMutating?: boolean;
  readonly onAssign?: jest.Mock;
  readonly onRemove?: jest.Mock;
  readonly onCreate?: jest.Mock;
}

function renderEditor(options: RenderOptions = {}) {
  const onAssign = options.onAssign ?? jest.fn();
  const onRemove = options.onRemove ?? jest.fn();
  const onCreate = options.onCreate ?? jest.fn().mockResolvedValue(undefined);

  const element = (overrides: RenderOptions = {}) => {
    const merged = { ...options, ...overrides };
    return (
      <TagsEditor
        assignedTags={merged.assigned ?? assignedTags}
        allTags={merged.all ?? allTags}
        isLoading={merged.isLoading ?? false}
        isError={merged.isError ?? false}
        isMutating={merged.isMutating ?? false}
        colors={COLORS}
        onAssign={onAssign}
        onRemove={onRemove}
        onCreate={onCreate}
        rootTestId='tags-editor'
      />
    );
  };

  const { rerender } = render(element());

  return {
    onAssign,
    onRemove,
    onCreate,
    rerenderWith: (overrides: RenderOptions) => rerender(element(overrides)),
  };
}

describe('TagsEditor', () => {
  it('renders assigned tags as colour-coded badges', () => {
    renderEditor();

    const workBadge = screen.getByTestId('tag-badge-1');
    expect(workBadge).toHaveTextContent('Work');
    expect(workBadge).toHaveStyle({ borderColor: '#3182CE' });
    expect(screen.getByTestId('tag-badge-2')).toHaveTextContent('Family');
  });

  it('renders a labelled remove button on each badge', () => {
    renderEditor();

    expect(
      screen.getByRole('button', { name: 'Remove tag Work' })
    ).toBeInTheDocument();
    expect(screen.getByTestId('remove-tag-1')).toBeInTheDocument();
    expect(screen.getByTestId('remove-tag-2')).toBeInTheDocument();
  });

  it('calls onRemove when the X is clicked', async () => {
    const user = userEvent.setup();
    const { onRemove } = renderEditor();

    await user.click(screen.getByTestId('remove-tag-1'));

    expect(onRemove).toHaveBeenCalledWith('1');
  });

  it('opens a searchable popover listing unassigned tags', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));

    expect(screen.getByTestId('tag-search-input')).toBeInTheDocument();
    // unassigned tags appear
    expect(screen.getByTestId('tag-option-3')).toBeInTheDocument();
    expect(screen.getByTestId('tag-option-4')).toBeInTheDocument();
    // already-assigned tags do not
    expect(screen.queryByTestId('tag-option-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tag-option-2')).not.toBeInTheDocument();
  });

  it('renders the hierarchy path for child tags in the option list', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));

    // Business is a child of Work
    expect(screen.getByTestId('tag-option-4')).toHaveTextContent(
      'Work › Business'
    );
  });

  it('calls onAssign when an existing option is selected', async () => {
    const user = userEvent.setup();
    const { onAssign } = renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    await user.click(screen.getByTestId('tag-option-3'));

    expect(onAssign).toHaveBeenCalledWith('3');
  });

  it('filters options by the search query', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    await user.type(screen.getByTestId('tag-search-input'), 'Friend');

    expect(screen.getByTestId('tag-option-3')).toBeInTheDocument();
    expect(screen.queryByTestId('tag-option-4')).not.toBeInTheDocument();
  });

  it('matches options ignoring leading/trailing whitespace in the query', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    // Trailing space must not empty the list or wrongly hide the create option
    await user.type(screen.getByTestId('tag-search-input'), 'Friends ');

    expect(screen.getByTestId('tag-option-3')).toBeInTheDocument();
    expect(screen.queryByTestId('create-tag-option')).not.toBeInTheDocument();
  });

  it('shows the Create option when the query matches no existing tag', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    await user.type(screen.getByTestId('tag-search-input'), 'NonExistentTag');

    expect(screen.getByTestId('create-tag-option')).toHaveTextContent(
      'NonExistentTag'
    );
  });

  it('calls onCreate with the typed name and the chosen colour', async () => {
    const user = userEvent.setup();
    const onCreate = jest.fn().mockResolvedValue(undefined);
    renderEditor({ onCreate });

    await user.click(screen.getByTestId('add-tag-button'));
    await user.type(screen.getByTestId('tag-search-input'), 'Holiday');
    await user.click(screen.getByTestId('create-tag-option'));

    // Choose a non-default colour
    await user.click(screen.getByTestId('colour-#DD6B20'));
    await user.click(screen.getByTestId('confirm-create-tag'));

    expect(onCreate).toHaveBeenCalledWith('Holiday', '#DD6B20');
  });

  it('keeps the create form open when onCreate rejects', async () => {
    const user = userEvent.setup();
    const onCreate = jest.fn().mockRejectedValue(new Error('Name exists'));
    renderEditor({ onCreate });

    await user.click(screen.getByTestId('add-tag-button'));
    await user.type(screen.getByTestId('tag-search-input'), 'Holiday');
    await user.click(screen.getByTestId('create-tag-option'));
    await user.click(screen.getByTestId('confirm-create-tag'));

    await waitFor(() => {
      expect(onCreate).toHaveBeenCalledWith('Holiday', expect.any(String));
    });
    // The create form stays open so the user can retry or amend
    expect(screen.getByTestId('confirm-create-tag')).toBeInTheDocument();
    expect(screen.getByTestId('new-tag-name-input')).toBeInTheDocument();
  });

  it('disables both create-form buttons while a mutation is in flight', async () => {
    const user = userEvent.setup();
    const { rerenderWith } = renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    await user.type(screen.getByTestId('tag-search-input'), 'Holiday');
    await user.click(screen.getByTestId('create-tag-option'));

    rerenderWith({ isMutating: true });

    // Cancel must not let the user leave mid-flight and have the resolving
    // mutation reset the popover underneath them.
    expect(screen.getByTestId('cancel-create-tag')).toBeDisabled();
    expect(screen.getByTestId('confirm-create-tag')).toBeDisabled();
  });

  it('keeps the Add Tag affordance reachable when there are no tags at all', () => {
    renderEditor({ assigned: [], all: [] });

    expect(screen.getByTestId('add-tag-button')).toBeInTheDocument();
    expect(screen.getByText('No tags assigned')).toBeInTheDocument();
  });

  it('exposes an aria-label on each colour swatch', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByTestId('add-tag-button'));
    await user.type(screen.getByTestId('tag-search-input'), 'Holiday');
    await user.click(screen.getByTestId('create-tag-option'));

    expect(
      screen.getByRole('button', { name: 'Select colour #DD6B20' })
    ).toBeInTheDocument();
  });

  it('shows the loading skeleton while data is loading', () => {
    renderEditor({ isLoading: true });

    expect(screen.getByTestId('tags-loading')).toBeInTheDocument();
  });

  it('shows the error state when tag definitions fail to load', () => {
    renderEditor({ isError: true });

    expect(screen.getByTestId('tags-error')).toBeInTheDocument();
    // The add affordance needs the definitions, so it stands down.
    expect(screen.queryByTestId('add-tag-button')).not.toBeInTheDocument();
  });

  it('keeps assigned badges visible and removable when tag definitions fail', async () => {
    // A caller may already hold the assigned tags (journal tags are embedded on
    // the journal resource). A failure of the *definitions* request must not
    // blank the badges the caller handed us, or the user loses the ability to
    // see and remove tags the page already has.
    const user = userEvent.setup();
    const { onRemove } = renderEditor({ isError: true });

    expect(screen.getByTestId('tag-badge-1')).toHaveTextContent('Work');
    expect(screen.getByTestId('tag-badge-2')).toHaveTextContent('Family');

    await user.click(screen.getByTestId('remove-tag-1'));

    expect(onRemove).toHaveBeenCalledWith('1');
  });
});
