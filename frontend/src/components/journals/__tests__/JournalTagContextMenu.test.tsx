/**
 * @jest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { JournalTagContextMenu } from '../JournalTagContextMenu';
import { useJournalTags, useUpdateJournalTag } from '@/lib/api/journals';
import type { JournalTag } from '@/types/journals';

jest.mock('@/lib/api/journals', () => ({
  useJournalTags: jest.fn(),
  useUpdateJournalTag: jest.fn(),
}));

const TAG: JournalTag = {
  id: '11111111-1111-1111-1111-111111111111',
  name: 'Climbing',
  color: '#3182CE',
  parent_id: null,
};

function renderMenu() {
  render(
    <JournalTagContextMenu tag={TAG}>
      {/* Stands in for the sidebar's tag link — what matters is that the
          wrapped row contains a focusable element. */}
      <a href='#climbing'>Climbing</a>
    </JournalTagContextMenu>
  );
}

describe('JournalTagContextMenu', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useJournalTags as jest.Mock).mockReturnValue({
      data: { data: [TAG] },
      isLoading: false,
      error: null,
    });
    (useUpdateJournalTag as jest.Mock).mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    });
  });

  it('offers Edit Tag when the tag row is right-clicked', async () => {
    renderMenu();

    fireEvent.contextMenu(screen.getByRole('link', { name: 'Climbing' }));

    expect(
      await screen.findByRole('menuitem', { name: /edit tag/i })
    ).toBeInTheDocument();
  });

  it('opens the management dialog from the menu item', async () => {
    const user = userEvent.setup();
    renderMenu();

    fireEvent.contextMenu(screen.getByRole('link', { name: 'Climbing' }));
    await user.click(
      await screen.findByRole('menuitem', { name: /edit tag/i })
    );

    expect(
      await screen.findByRole('dialog', { name: 'Edit Tag' })
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/i)).toHaveValue('Climbing');
  });

  it('keeps the dialog closed until the menu item is chosen', () => {
    renderMenu();

    expect(
      screen.queryByRole('dialog', { name: 'Edit Tag' })
    ).not.toBeInTheDocument();
  });

  it('is operable from the keyboard once open', async () => {
    // The trigger wraps the focusable tag link, so the keyboard context-menu
    // key raises the same `contextmenu` event a right-click does. From there
    // the menu must be usable without a pointer.
    const user = userEvent.setup();
    renderMenu();

    const link = screen.getByRole('link', { name: 'Climbing' });
    link.focus();
    expect(link).toHaveFocus();

    fireEvent.contextMenu(link);

    const editItem = await screen.findByRole('menuitem', { name: /edit tag/i });

    // Arrow keys walk the menu and Enter activates — no pointer involved.
    await user.keyboard('{ArrowDown}');
    await waitFor(() => expect(editItem).toHaveFocus());

    await user.keyboard('{Enter}');

    expect(
      await screen.findByRole('dialog', { name: 'Edit Tag' })
    ).toBeInTheDocument();
  });

  it('closes the menu on Escape without opening the dialog', async () => {
    const user = userEvent.setup();
    renderMenu();

    fireEvent.contextMenu(screen.getByRole('link', { name: 'Climbing' }));
    await screen.findByRole('menuitem', { name: /edit tag/i });

    await user.keyboard('{Escape}');

    await waitFor(() => {
      expect(
        screen.queryByRole('menuitem', { name: /edit tag/i })
      ).not.toBeInTheDocument();
    });
    expect(
      screen.queryByRole('dialog', { name: 'Edit Tag' })
    ).not.toBeInTheDocument();
  });
});
