/** @jest-environment jsdom */
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContactSuggestionsCard } from '../ContactSuggestionsCard';
import {
  useAcceptContactSuggestion,
  useContactSuggestions,
  useIgnoreContactSuggestion,
  useIgnoredContactSuggestions,
  useUnignoreContactSuggestion,
} from '@/lib/api/contact-suggestions';
import type {
  ContactSuggestionResource,
  IgnoredContactSuggestionResource,
} from '@/types/contact-suggestions';

jest.mock('@/lib/api/contact-suggestions', () => ({
  useContactSuggestions: jest.fn(),
  useIgnoredContactSuggestions: jest.fn(),
  useAcceptContactSuggestion: jest.fn(),
  useIgnoreContactSuggestion: jest.fn(),
  useUnignoreContactSuggestion: jest.fn(),
}));

// The real combobox searches the contacts API; picking a contact is all the
// card needs from it.
jest.mock('@/components/contacts/ContactSearchCombobox', () => ({
  ContactSearchCombobox: ({
    onSelect,
    disabled,
    inputId,
  }: {
    onSelect: (contact: { id: string }) => void;
    disabled?: boolean;
    inputId?: string;
  }) => (
    <button
      type='button'
      id={inputId}
      disabled={disabled}
      onClick={() => onSelect({ id: '42' })}
    >
      Pick Jane Doe
    </button>
  ),
}));

const acceptMutate = jest.fn();
const ignoreMutate = jest.fn();
const unignoreMutate = jest.fn();

function suggestion(
  email: string,
  displayName: string | null,
  eventCount: number
): ContactSuggestionResource {
  return {
    type: 'contact-suggestions',
    id: email,
    attributes: {
      email,
      display_name: displayName,
      event_count: eventCount,
      last_seen_at: '2026-09-01T09:00:00Z',
    },
  };
}

function ignored(email: string): IgnoredContactSuggestionResource {
  return {
    type: 'ignored-contact-suggestions',
    id: email,
    attributes: { email, provenance: 'ui', created_at: null },
  };
}

function mockLists(
  suggestions: ContactSuggestionResource[],
  ignoredList: IgnoredContactSuggestionResource[] = []
) {
  (useContactSuggestions as jest.Mock).mockReturnValue({
    data: { data: suggestions },
    isLoading: false,
    error: null,
  });
  (useIgnoredContactSuggestions as jest.Mock).mockReturnValue({
    data: { data: ignoredList },
    isLoading: false,
    error: null,
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  (useAcceptContactSuggestion as jest.Mock).mockReturnValue({
    mutate: acceptMutate,
    isPending: false,
  });
  (useIgnoreContactSuggestion as jest.Mock).mockReturnValue({
    mutate: ignoreMutate,
    isPending: false,
  });
  (useUnignoreContactSuggestion as jest.Mock).mockReturnValue({
    mutate: unignoreMutate,
    isPending: false,
  });
});

describe('ContactSuggestionsCard', () => {
  it('lists each suggestion with its name, email and event count', () => {
    mockLists([
      suggestion('jane@x.com', 'Jane Smith', 6),
      suggestion('anon@x.com', null, 5),
    ]);

    render(<ContactSuggestionsCard />);

    const jane = screen.getByRole('listitem', { name: 'jane@x.com' });
    expect(within(jane).getByText('Jane Smith')).toBeInTheDocument();
    expect(within(jane).getByText(/jane@x\.com/)).toBeInTheDocument();
    expect(within(jane).getByText('Seen on 6 events')).toBeInTheDocument();
    const anon = screen.getByRole('listitem', { name: 'anon@x.com' });
    expect(within(anon).getByText('Seen on 5 events')).toBeInTheDocument();
  });

  it('says so when there are no suggestions', () => {
    mockLists([]);

    render(<ContactSuggestionsCard />);

    expect(screen.getByText(/no suggestions right now/i)).toBeInTheDocument();
  });

  it('ignores a suggestion', async () => {
    const user = userEvent.setup();
    mockLists([suggestion('jane@x.com', 'Jane Smith', 6)]);

    render(<ContactSuggestionsCard />);
    await user.click(screen.getByRole('button', { name: 'Ignore jane@x.com' }));

    expect(ignoreMutate).toHaveBeenCalledWith('jane@x.com');
  });

  it('creates a contact prefilled from the display name', async () => {
    const user = userEvent.setup();
    mockLists([suggestion('jane@x.com', 'Jane Smith', 6)]);

    render(<ContactSuggestionsCard />);
    await user.click(
      screen.getByRole('button', { name: 'Create contact for jane@x.com' })
    );
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByLabelText('First name')).toHaveValue('Jane');
    expect(within(dialog).getByLabelText('Last name')).toHaveValue('Smith');
    await user.click(
      within(dialog).getByRole('button', { name: 'Create contact' })
    );

    expect(acceptMutate).toHaveBeenCalledWith(
      {
        email: 'jane@x.com',
        target: { kind: 'new', first_name: 'Jane', last_name: 'Smith' },
      },
      expect.anything()
    );
  });

  it('requires a first name to create a contact', async () => {
    const user = userEvent.setup();
    mockLists([suggestion('anon@x.com', null, 5)]);

    render(<ContactSuggestionsCard />);
    await user.click(
      screen.getByRole('button', { name: 'Create contact for anon@x.com' })
    );
    const dialog = screen.getByRole('dialog');
    await user.click(
      within(dialog).getByRole('button', { name: 'Create contact' })
    );

    expect(
      await within(dialog).findByText('First name is required')
    ).toBeInTheDocument();
    expect(acceptMutate).not.toHaveBeenCalled();
  });

  it('adds the email to an existing contact', async () => {
    const user = userEvent.setup();
    mockLists([suggestion('jane@x.com', 'Jane Smith', 6)]);

    render(<ContactSuggestionsCard />);
    await user.click(
      screen.getByRole('button', {
        name: 'Add jane@x.com to an existing contact',
      })
    );
    await user.click(
      within(screen.getByRole('dialog')).getByLabelText('Contact')
    );

    expect(acceptMutate).toHaveBeenCalledWith(
      { email: 'jane@x.com', target: { kind: 'existing', contact_id: 42 } },
      expect.anything()
    );
  });

  it("keeps another suggestion's dialog open when an earlier accept succeeds", async () => {
    const user = userEvent.setup();
    mockLists([
      suggestion('jane@x.com', 'Jane Smith', 6),
      suggestion('sam@x.com', 'Sam Jones', 5),
    ]);

    render(<ContactSuggestionsCard />);
    await user.click(
      screen.getByRole('button', { name: 'Create contact for jane@x.com' })
    );
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', {
        name: 'Create contact',
      })
    );
    const [, { onSuccess }] = acceptMutate.mock.calls[0] as [
      unknown,
      { onSuccess: () => void },
    ];
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' })
    );
    await user.click(
      screen.getByRole('button', { name: 'Create contact for sam@x.com' })
    );

    act(() => onSuccess());

    expect(
      within(screen.getByRole('dialog')).getByLabelText('First name')
    ).toHaveValue('Sam');
  });

  it('shows an error when the ignored list fails to load', () => {
    mockLists([suggestion('jane@x.com', 'Jane Smith', 6)]);
    (useIgnoredContactSuggestions as jest.Mock).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Server unavailable'),
    });

    render(<ContactSuggestionsCard />);

    expect(
      screen.getByText('Error loading ignored suggestions')
    ).toBeInTheDocument();
    expect(screen.getByText('Server unavailable')).toBeInTheDocument();
  });

  it('names the contact search and stops a second pick while saving', async () => {
    const user = userEvent.setup();
    mockLists([suggestion('jane@x.com', 'Jane Smith', 6)]);
    (useAcceptContactSuggestion as jest.Mock).mockReturnValue({
      mutate: acceptMutate,
      isPending: true,
    });

    render(<ContactSuggestionsCard />);
    await user.click(
      screen.getByRole('button', {
        name: 'Add jane@x.com to an existing contact',
      })
    );

    const dialog = within(screen.getByRole('dialog'));
    expect(dialog.getByLabelText('Contact')).toBeDisabled();
  });

  it('restores an ignored email', async () => {
    const user = userEvent.setup();
    mockLists([], [ignored('noisy@x.com')]);

    render(<ContactSuggestionsCard />);
    await user.click(screen.getByRole('button', { name: 'Ignored (1)' }));
    await user.click(
      screen.getByRole('button', { name: 'Restore noisy@x.com' })
    );

    expect(unignoreMutate).toHaveBeenCalledWith('noisy@x.com');
  });
});
