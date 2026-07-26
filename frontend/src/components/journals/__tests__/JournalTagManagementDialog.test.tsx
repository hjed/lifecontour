/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { JournalTagManagementDialog } from '../JournalTagManagementDialog';
import {
  useJournalTags,
  useUpdateJournalTag,
  useDeleteJournalTag,
  useMergeJournalTag,
} from '@/lib/api/journals';
import type { JournalTag } from '@/types/journals';

jest.mock('@/lib/api/journals', () => ({
  useJournalTags: jest.fn(),
  useUpdateJournalTag: jest.fn(),
  useDeleteJournalTag: jest.fn(),
  useMergeJournalTag: jest.fn(),
}));

const mockUpdateTag = jest.fn();
const mockDeleteTag = jest.fn();
const mockMergeTag = jest.fn();

const OUTDOORS = '11111111-1111-1111-1111-111111111111';
const CLIMBING = '22222222-2222-2222-2222-222222222222';
const BOULDERING = '33333333-3333-3333-3333-333333333333';
const COOKING = '44444444-4444-4444-4444-444444444444';

const ALL_TAGS: JournalTag[] = [
  { id: OUTDOORS, name: 'Outdoors', color: '#38A169', parent_id: null },
  {
    id: CLIMBING,
    name: 'Climbing',
    color: '#3182CE',
    description: 'Rock climbing entries',
    parent_id: OUTDOORS,
  },
  { id: BOULDERING, name: 'Bouldering', color: '#805AD5', parent_id: CLIMBING },
  { id: COOKING, name: 'Cooking', color: '#D69E2E', parent_id: null },
];

function tagById(id: string): JournalTag {
  return ALL_TAGS.find(tag => tag.id === id)!;
}

function renderDialog(tag: JournalTag, onOpenChange = jest.fn()) {
  render(
    <JournalTagManagementDialog open onOpenChange={onOpenChange} tag={tag} />
  );
  return { onOpenChange };
}

describe('JournalTagManagementDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUpdateTag.mockResolvedValue({ data: { id: CLIMBING } });
    mockDeleteTag.mockResolvedValue(undefined);
    mockMergeTag.mockResolvedValue(undefined);
    (useJournalTags as jest.Mock).mockReturnValue({
      data: { data: ALL_TAGS },
      isLoading: false,
      error: null,
    });
    (useUpdateJournalTag as jest.Mock).mockReturnValue({
      mutateAsync: mockUpdateTag,
      isPending: false,
    });
    (useDeleteJournalTag as jest.Mock).mockReturnValue({
      mutateAsync: mockDeleteTag,
      isPending: false,
    });
    (useMergeJournalTag as jest.Mock).mockReturnValue({
      mutateAsync: mockMergeTag,
      isPending: false,
    });
  });

  it('pre-populates the form from the tag being edited', () => {
    renderDialog(tagById(CLIMBING));

    expect(
      screen.getByRole('dialog', { name: 'Edit Tag' })
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/i)).toHaveValue('Climbing');
    expect(screen.getByLabelText(/Description/i)).toHaveValue(
      'Rock climbing entries'
    );
    expect(screen.getByPlaceholderText('#000000')).toHaveValue('#3182CE');
    expect(screen.getByLabelText('Parent Tag')).toHaveTextContent('Outdoors');
  });

  it('sends the renamed tag to the update endpoint', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog(tagById(CLIMBING));

    const nameInput = screen.getByLabelText(/^Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Sport Climbing');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      // `description` is absent because it was not edited — omitted attributes
      // are left untouched by the API, and sending an unchanged value would
      // register as a change against a null stored description.
      expect(mockUpdateTag).toHaveBeenCalledWith({
        id: CLIMBING,
        attributes: {
          name: 'Sport Climbing',
          color: '#3182CE',
          parent_id: OUTDOORS,
        },
      });
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('sends an explicit null parent when the tag is moved to the root', async () => {
    const user = userEvent.setup();
    renderDialog(tagById(CLIMBING));

    await user.click(screen.getByLabelText('Parent Tag'));
    await user.click(
      await screen.findByRole('option', { name: 'None (Root Level)' })
    );
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(mockUpdateTag).toHaveBeenCalledWith(
        expect.objectContaining({
          attributes: expect.objectContaining({ parent_id: null }),
        })
      );
    });
  });

  it('excludes the tag itself and its descendants from the parent options', async () => {
    const user = userEvent.setup();
    renderDialog(tagById(CLIMBING));

    await user.click(screen.getByLabelText('Parent Tag'));

    // Unrelated tags remain selectable...
    expect(
      await screen.findByRole('option', { name: 'Cooking' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('option', { name: 'Outdoors' })
    ).toBeInTheDocument();
    // ...but the tag itself and its child would create a cycle.
    expect(
      screen.queryByRole('option', { name: 'Climbing' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: 'Bouldering' })
    ).not.toBeInTheDocument();
  });

  it('omits colour entirely for a tag that has none', async () => {
    // Sending '' would fail `JournalTag._validate_color` and 400 the whole
    // edit, so a colourless tag created via the API stays editable.
    const colourless: JournalTag = {
      id: COOKING,
      name: 'Cooking',
      color: null,
      parent_id: null,
    };
    (useJournalTags as jest.Mock).mockReturnValue({
      data: { data: [colourless] },
      isLoading: false,
      error: null,
    });

    const user = userEvent.setup();
    renderDialog(colourless);

    const nameInput = screen.getByLabelText(/^Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Baking');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(mockUpdateTag).toHaveBeenCalled();
    });
    const attributes = mockUpdateTag.mock.calls[0][0].attributes;
    expect(attributes).not.toHaveProperty('color');
    expect(attributes.name).toBe('Baking');
  });

  it('allows a name longer than the contacts limit, up to the journal API cap', async () => {
    // A tag created through the API or MCP can carry a 51–100 character name;
    // the dialog must not block editing its colour because of it.
    const longName = 'x'.repeat(80);
    const longNamed: JournalTag = {
      id: COOKING,
      name: longName,
      color: '#D69E2E',
      parent_id: null,
    };
    (useJournalTags as jest.Mock).mockReturnValue({
      data: { data: [longNamed] },
      isLoading: false,
      error: null,
    });

    const user = userEvent.setup();
    renderDialog(longNamed);

    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(mockUpdateTag).toHaveBeenCalledWith(
        expect.objectContaining({
          attributes: expect.objectContaining({ name: longName }),
        })
      );
    });
  });

  it('omits an untouched description rather than rewriting null to an empty string', async () => {
    // The service treats '' as different from null, so sending the normalised
    // empty description would record a change the user never made.
    const undescribed: JournalTag = {
      id: COOKING,
      name: 'Cooking',
      color: '#D69E2E',
      parent_id: null,
    };
    (useJournalTags as jest.Mock).mockReturnValue({
      data: { data: [undescribed] },
      isLoading: false,
      error: null,
    });

    const user = userEvent.setup();
    renderDialog(undescribed);

    const nameInput = screen.getByLabelText(/^Name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'Baking');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(mockUpdateTag).toHaveBeenCalled();
    });
    expect(mockUpdateTag.mock.calls[0][0].attributes).not.toHaveProperty(
      'description'
    );
  });

  it('still sends an emptied description when the user clears real text', async () => {
    const user = userEvent.setup();
    renderDialog(tagById(CLIMBING));

    await user.clear(screen.getByLabelText(/Description/i));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => {
      expect(mockUpdateTag).toHaveBeenCalledWith(
        expect.objectContaining({
          attributes: expect.objectContaining({ description: '' }),
        })
      );
    });
  });

  it('re-seeds the form when the subject tag changes to one with identical attributes', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <JournalTagManagementDialog
        open
        onOpenChange={jest.fn()}
        tag={tagById(CLIMBING)}
      />
    );

    await user.clear(screen.getByLabelText(/^Name/i));
    await user.type(screen.getByLabelText(/^Name/i), 'Half typed');

    rerender(
      <JournalTagManagementDialog
        open
        onOpenChange={jest.fn()}
        tag={{ ...tagById(CLIMBING), id: BOULDERING }}
      />
    );

    expect(screen.getByLabelText(/^Name/i)).toHaveValue('Climbing');
  });

  it('blocks the update when the name is cleared', async () => {
    const user = userEvent.setup();
    renderDialog(tagById(CLIMBING));

    await user.clear(screen.getByLabelText(/^Name/i));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    expect(await screen.findByText('Name is required')).toBeInTheDocument();
    expect(mockUpdateTag).not.toHaveBeenCalled();
  });

  describe('delete', () => {
    it('warns that the tag is removed from every journal before deleting', async () => {
      const user = userEvent.setup();
      renderDialog(tagById(CLIMBING));

      await user.click(screen.getByRole('button', { name: 'Delete Tag' }));

      const confirmation = screen.getByRole('alertdialog');
      expect(confirmation).toHaveTextContent('Climbing');
      expect(confirmation).toHaveTextContent(
        /remove it from all journals it is assigned to/i
      );
      // Nothing is destroyed until the confirmation is accepted.
      expect(mockDeleteTag).not.toHaveBeenCalled();
    });

    it('deletes the tag and closes the dialog once confirmed', async () => {
      const user = userEvent.setup();
      const { onOpenChange } = renderDialog(tagById(CLIMBING));

      await user.click(screen.getByRole('button', { name: 'Delete Tag' }));
      await user.click(screen.getByRole('button', { name: 'Delete' }));

      await waitFor(() => {
        expect(mockDeleteTag).toHaveBeenCalledWith(CLIMBING);
      });
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  describe('merge', () => {
    it('offers no merge target until one is chosen', () => {
      renderDialog(tagById(CLIMBING));

      expect(screen.getByRole('button', { name: 'Merge' })).toBeDisabled();
    });

    it('excludes the tag itself and its descendants from the merge targets', async () => {
      // The backend rejects a self-merge and a descendant-merge with a 400 —
      // the surviving hierarchy would run through a deleted tag — so neither is
      // ever offered.
      const user = userEvent.setup();
      renderDialog(tagById(CLIMBING));

      await user.click(screen.getByLabelText('Merge into'));

      expect(
        await screen.findByRole('option', { name: 'Cooking' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('option', { name: 'Outdoors' })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('option', { name: 'Climbing' })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('option', { name: 'Bouldering' })
      ).not.toBeInTheDocument();
    });

    it('merges into the chosen target after confirmation and closes the dialog', async () => {
      const user = userEvent.setup();
      const { onOpenChange } = renderDialog(tagById(CLIMBING));

      await user.click(screen.getByLabelText('Merge into'));
      await user.click(await screen.findByRole('option', { name: 'Cooking' }));
      await user.click(screen.getByRole('button', { name: 'Merge' }));

      // Confirmation is required for the merge, as it is for the delete.
      expect(mockMergeTag).not.toHaveBeenCalled();

      await user.click(screen.getByRole('button', { name: 'Confirm Merge' }));

      await waitFor(() => {
        expect(mockMergeTag).toHaveBeenCalledWith({
          sourceId: CLIMBING,
          targetId: COOKING,
        });
      });
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});
