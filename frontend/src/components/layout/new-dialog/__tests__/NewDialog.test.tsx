/**
 * @jest-environment jsdom
 */

import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BookOpen, User } from 'lucide-react';

import { NewDialog } from '../NewDialog';
import type { NewEntityPanelProps, NewEntityType } from '../types';

/**
 * A stand-in panel with one labelled input, so a test can type into a type's
 * form, switch away and back, and see whether the value survived.
 */
function makeFakePanel(label: string) {
  function FakePanel({ onCreated, onCancel }: NewEntityPanelProps) {
    return (
      <div>
        <label>
          {label} name
          <input />
        </label>
        <button type='button' onClick={onCreated}>
          Create {label}
        </button>
        <button type='button' onClick={onCancel}>
          Cancel {label}
        </button>
      </div>
    );
  }
  return FakePanel;
}

/**
 * Two types rather than the one the app ships with, so switching and input
 * retention are proven before a second real type exists. The ids are cast
 * because the production union only names the types the app registers.
 */
/** Lets a test settle a panel's create after the dialog has moved on. */
let settleSlowCreate: () => void = () => {};

function SlowPanel({ onCreated }: NewEntityPanelProps) {
  return (
    <button
      type='button'
      onClick={() => {
        settleSlowCreate = onCreated;
      }}
    >
      Start slow create
    </button>
  );
}

const TWO_TYPES: readonly NewEntityType[] = [
  {
    id: 'contact',
    label: 'Alpha',
    icon: User,
    Panel: makeFakePanel('Alpha'),
  },
  {
    id: 'beta' as NewEntityType['id'],
    label: 'Beta',
    icon: BookOpen,
    Panel: makeFakePanel('Beta'),
  },
];

function renderDialog() {
  const user = userEvent.setup();
  render(<NewDialog types={TWO_TYPES} />);
  return { user, trigger: screen.getByRole('button', { name: 'New' }) };
}

async function openDialog() {
  const rendered = renderDialog();
  await rendered.user.click(rendered.trigger);
  return { ...rendered, dialog: await screen.findByRole('dialog') };
}

/** A panel whose save the test starts and finishes by hand. */
function SavingPanel({ onBusyChange }: NewEntityPanelProps) {
  return (
    <div>
      <button type='button' onClick={() => onBusyChange(true)}>
        Start saving
      </button>
      <button type='button' onClick={() => onBusyChange(false)}>
        Finish saving
      </button>
    </div>
  );
}

const SAVING_TYPES: readonly NewEntityType[] = [
  { ...TWO_TYPES[0], Panel: SavingPanel },
  TWO_TYPES[1],
];

describe('NewDialog', () => {
  it('renders a New trigger that announces a dialog', () => {
    const { trigger } = renderDialog();

    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens a dialog named New with one switch button per type, in order', async () => {
    const { trigger, dialog } = await openDialog();

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(dialog).toHaveAccessibleName('New');

    const group = within(dialog).getByRole('group', {
      name: 'What to create',
    });
    const buttons = within(group).getAllByRole('button');
    expect(buttons.map(button => button.textContent)).toEqual([
      'Alpha',
      'Beta',
    ]);
  });

  it('selects the first type by default and shows only its panel', async () => {
    const { dialog } = await openDialog();

    expect(
      within(dialog).getByRole('button', { name: 'Alpha' })
    ).toHaveAttribute('aria-pressed', 'true');
    expect(
      within(dialog).getByRole('button', { name: 'Beta' })
    ).toHaveAttribute('aria-pressed', 'false');
    expect(within(dialog).getByLabelText('Alpha name')).toBeVisible();
    expect(within(dialog).getByLabelText('Beta name')).not.toBeVisible();
  });

  it('switches the visible panel when another type is pressed', async () => {
    const { user, dialog } = await openDialog();

    await user.click(within(dialog).getByRole('button', { name: 'Beta' }));

    expect(
      within(dialog).getByRole('button', { name: 'Beta' })
    ).toHaveAttribute('aria-pressed', 'true');
    expect(
      within(dialog).getByRole('button', { name: 'Alpha' })
    ).toHaveAttribute('aria-pressed', 'false');
    expect(within(dialog).getByLabelText('Beta name')).toBeVisible();
    expect(within(dialog).getByLabelText('Alpha name')).not.toBeVisible();
  });

  it('keeps what was typed in each type across switches', async () => {
    const { user, dialog } = await openDialog();

    await user.type(within(dialog).getByLabelText('Alpha name'), 'first');
    await user.click(within(dialog).getByRole('button', { name: 'Beta' }));
    await user.type(within(dialog).getByLabelText('Beta name'), 'second');
    await user.click(within(dialog).getByRole('button', { name: 'Alpha' }));

    expect(within(dialog).getByLabelText('Alpha name')).toHaveValue('first');
    expect(within(dialog).getByLabelText('Beta name')).toHaveValue('second');
  });

  it('points each switch button at an existing panel', async () => {
    const { dialog } = await openDialog();

    const group = within(dialog).getByRole('group', {
      name: 'What to create',
    });
    for (const button of within(group).getAllByRole('button')) {
      const panelId = button.getAttribute('aria-controls');
      expect(panelId).toBeTruthy();
      const panel = document.getElementById(panelId ?? '');
      expect(panel).not.toBeNull();
      expect(dialog).toContainElement(panel);
    }
  });

  it('closes when a panel reports it created something', async () => {
    const { user, dialog } = await openDialog();

    await user.click(
      within(dialog).getByRole('button', { name: 'Create Alpha' })
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('closes when a panel is cancelled', async () => {
    const { user, dialog } = await openDialog();

    await user.click(
      within(dialog).getByRole('button', { name: 'Cancel Alpha' })
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    const { user, trigger } = await openDialog();

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('closes from its Close button', async () => {
    const { user, dialog } = await openDialog();

    await user.click(within(dialog).getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('discards what was typed once the dialog closes', async () => {
    const { user, trigger, dialog } = await openDialog();

    await user.type(within(dialog).getByLabelText('Alpha name'), 'draft');
    await user.keyboard('{Escape}');
    await user.click(trigger);

    expect(
      within(await screen.findByRole('dialog')).getByLabelText('Alpha name')
    ).toHaveValue('');
  });

  it('starts on the first type again when reopened', async () => {
    const { user, trigger, dialog } = await openDialog();

    await user.click(within(dialog).getByRole('button', { name: 'Beta' }));
    await user.keyboard('{Escape}');
    await user.click(trigger);

    const reopened = await screen.findByRole('dialog');
    expect(
      within(reopened).getByRole('button', { name: 'Alpha' })
    ).toHaveAttribute('aria-pressed', 'true');
    expect(within(reopened).getByLabelText('Alpha name')).toBeVisible();
  });

  it('ignores a create that finishes after its opening was closed', async () => {
    const user = userEvent.setup();
    render(
      <NewDialog
        types={[{ id: 'contact', label: 'Slow', icon: User, Panel: SlowPanel }]}
      />
    );
    const trigger = screen.getByRole('button', { name: 'New' });

    await user.click(trigger);
    await user.click(
      await screen.findByRole('button', { name: 'Start slow create' })
    );
    await user.keyboard('{Escape}');
    await user.click(trigger);
    await screen.findByRole('dialog');

    act(() => settleSlowCreate());

    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});

describe('NewDialog while a panel is saving', () => {
  async function openSavingDialog() {
    const user = userEvent.setup();
    render(<NewDialog types={SAVING_TYPES} />);
    await user.click(screen.getByRole('button', { name: 'New' }));
    return { user, dialog: await screen.findByRole('dialog') };
  }

  it('locks the other types until the save finishes', async () => {
    const { user, dialog } = await openSavingDialog();
    const alpha = within(dialog).getByRole('button', { name: 'Alpha' });
    const beta = within(dialog).getByRole('button', { name: 'Beta' });

    await user.click(
      within(dialog).getByRole('button', { name: 'Start saving' })
    );

    expect(beta).toBeDisabled();
    expect(alpha).toHaveAttribute('aria-pressed', 'true');
    expect(within(dialog).getByRole('status')).toHaveTextContent('Saving');
    await user.click(beta);
    expect(alpha).toHaveAttribute('aria-pressed', 'true');

    await user.click(
      within(dialog).getByRole('button', { name: 'Finish saving' })
    );

    expect(beta).toBeEnabled();
    expect(within(dialog).getByRole('status')).toBeEmptyDOMElement();
    await user.click(beta);
    expect(beta).toHaveAttribute('aria-pressed', 'true');
  });

  it('starts unlocked on the next opening', async () => {
    const { user, dialog } = await openSavingDialog();
    await user.click(
      within(dialog).getByRole('button', { name: 'Start saving' })
    );
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: 'New' }));
    const reopened = await screen.findByRole('dialog');

    expect(
      within(reopened).getByRole('button', { name: 'Beta' })
    ).toBeEnabled();
  });
});

/**
 * A panel that, like the Task panel, puts the cursor in its own first field
 * when told it is the one shown on open.
 */
function makeFocusingPanel(label: string) {
  function FocusingPanel({ shownOnOpen }: NewEntityPanelProps) {
    return (
      <label>
        {label} text
        {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the behaviour under test */}
        <input autoFocus={shownOnOpen} />
      </label>
    );
  }
  return FocusingPanel;
}

describe('NewDialog focus on open', () => {
  it('tells only the panel shown on open to take focus, and lets it keep it', async () => {
    const user = userEvent.setup();
    render(
      <NewDialog
        types={[
          {
            id: 'contact',
            label: 'Alpha',
            icon: User,
            Panel: makeFocusingPanel('Alpha'),
            focusesOnOpen: true,
          },
          {
            id: 'beta' as NewEntityType['id'],
            label: 'Beta',
            icon: BookOpen,
            Panel: makeFocusingPanel('Beta'),
          },
        ]}
      />
    );

    await user.click(screen.getByRole('button', { name: 'New' }));
    const dialog = await screen.findByRole('dialog');

    // Radix would otherwise move focus to the first tabbable node, the Close
    // button, after the panel had already taken it.
    expect(within(dialog).getByLabelText('Alpha text')).toHaveFocus();
  });

  it('leaves focus to the dialog when the first type does not take it', async () => {
    const user = userEvent.setup();
    render(<NewDialog types={TWO_TYPES} />);

    await user.click(screen.getByRole('button', { name: 'New' }));
    const dialog = await screen.findByRole('dialog');

    expect(within(dialog).getByRole('button', { name: 'Close' })).toHaveFocus();
  });
});
