import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  MergeContactResolutionDialog,
  detectContactConflicts,
} from '../MergeContactResolutionDialog';
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

describe('MergeContactResolutionDialog', () => {
  const survivor = buildContact('1', {
    first_name: 'Survivor First',
    last_name: 'Survivor Last',
    nick_name: 'SurvNick',
    is_favourite: false,
  });

  const source = buildContact('2', {
    first_name: 'Source First',
    last_name: 'Source Last',
    nick_name: 'SrcNick',
    is_favourite: true, // differs but must NOT be a conflict
  });

  const mockOnResolve = jest.fn();
  const mockOnOpenChange = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('detectContactConflicts: surfaces differing text fields, ignores is_favourite and empties', () => {
    const conflicts = detectContactConflicts(survivor, source);
    const fieldIds = conflicts.map(c => c.fieldId).sort();
    expect(fieldIds).toEqual(['first_name', 'last_name', 'nick_name']);
    // is_favourite differs but is excluded
    expect(fieldIds).not.toContain('is_favourite');
  });

  it('renders a conflict block per differing field with both values', () => {
    render(
      <MergeContactResolutionDialog
        survivorContact={survivor}
        sourceContact={source}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    expect(screen.getByText('Resolve Merge Conflicts')).toBeInTheDocument();

    expect(screen.getByText('First Name')).toBeInTheDocument();
    expect(screen.getByText('Last Name')).toBeInTheDocument();
    expect(screen.getByText('Nickname')).toBeInTheDocument();

    expect(screen.getByText('Survivor First')).toBeInTheDocument();
    expect(screen.getByText('Source First')).toBeInTheDocument();
    expect(screen.getByText('Survivor Last')).toBeInTheDocument();
    expect(screen.getByText('Source Last')).toBeInTheDocument();

    // is_favourite must not appear as a conflict block
    expect(screen.queryByText('Favourite')).not.toBeInTheDocument();

    // Defaults to survivor (target) values
    expect(screen.getByTestId('radio-target-first_name')).toBeChecked();
  });

  it('builds the override object from radio selections on submit', async () => {
    const user = userEvent.setup();
    render(
      <MergeContactResolutionDialog
        survivorContact={survivor}
        sourceContact={source}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    // Take the source value for first_name; leave the rest as survivor
    await user.click(screen.getByTestId('radio-source-first_name'));

    await user.click(
      screen.getByRole('button', { name: /resolve and merge/i })
    );

    expect(mockOnResolve).toHaveBeenCalledWith({
      first_name: 'Source First',
      last_name: 'Survivor Last',
      nick_name: 'SurvNick',
    });
  });

  it('honours a custom value typed into the input', async () => {
    const user = userEvent.setup();
    render(
      <MergeContactResolutionDialog
        survivorContact={survivor}
        sourceContact={source}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    await user.click(screen.getByTestId('radio-custom-nick_name'));
    const input = screen.getByPlaceholderText(/enter custom nickname/i);
    await user.type(input, 'CustomNick');

    await user.click(
      screen.getByRole('button', { name: /resolve and merge/i })
    );

    expect(mockOnResolve).toHaveBeenCalledWith(
      expect.objectContaining({ nick_name: 'CustomNick' })
    );
  });

  it('sends an empty string when Custom is selected without typing', async () => {
    const user = userEvent.setup();
    render(
      <MergeContactResolutionDialog
        survivorContact={survivor}
        sourceContact={source}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    // Explicitly choose Custom but leave the input empty.
    await user.click(screen.getByTestId('radio-custom-nick_name'));

    await user.click(
      screen.getByRole('button', { name: /resolve and merge/i })
    );

    expect(mockOnResolve).toHaveBeenCalledWith(
      expect.objectContaining({ nick_name: '' })
    );
  });

  it('re-detects conflicts and defaults new selections when contacts change', async () => {
    const user = userEvent.setup();
    const survivorA = buildContact('1', { first_name: 'Alice' });
    const sourceA = buildContact('2', { first_name: 'Bob' });
    const { rerender } = render(
      <MergeContactResolutionDialog
        survivorContact={survivorA}
        sourceContact={sourceA}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    // Swap in a different pair that introduces a brand-new conflicting field.
    const survivorB = buildContact('3', {
      first_name: 'Carol',
      last_name: 'Smith',
    });
    const sourceB = buildContact('4', {
      first_name: 'Dave',
      last_name: 'Jones',
    });
    rerender(
      <MergeContactResolutionDialog
        survivorContact={survivorB}
        sourceContact={sourceB}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    // The newly detected last_name conflict must have a default selection so it
    // is not silently skipped on submit.
    expect(screen.getByTestId('radio-target-last_name')).toBeChecked();

    await user.click(
      screen.getByRole('button', { name: /resolve and merge/i })
    );

    expect(mockOnResolve).toHaveBeenCalledWith({
      first_name: 'Carol',
      last_name: 'Smith',
    });
  });

  it('shows the no-conflict confirm state and resolves with empty overrides', async () => {
    const user = userEvent.setup();
    const identical = buildContact('1', {
      first_name: 'Same',
      last_name: 'Person',
    });
    const identicalSource = buildContact('2', {
      first_name: 'Same',
      last_name: 'Person',
    });

    render(
      <MergeContactResolutionDialog
        survivorContact={identical}
        sourceContact={identicalSource}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    expect(screen.getByText('Confirm Merge')).toBeInTheDocument();
    expect(screen.getByText(/No conflicts detected/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^merge$/i }));
    expect(mockOnResolve).toHaveBeenCalledWith({});
  });

  it('renders a loading state when either contact is null', () => {
    render(
      <MergeContactResolutionDialog
        survivorContact={null}
        sourceContact={null}
        open={true}
        isPending={false}
        onOpenChange={mockOnOpenChange}
        onResolve={mockOnResolve}
      />
    );

    expect(screen.getByText(/Comparing contacts/i)).toBeInTheDocument();
  });
});
