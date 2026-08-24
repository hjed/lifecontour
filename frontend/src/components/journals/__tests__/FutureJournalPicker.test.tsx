/**
 * Tests for the future-journal picker.
 *
 * The specification asks for "a picker, not a journal browser": recent and
 * near-future journals first, searchable by title and date, and **never** a
 * bare date picker — a task is due *in a journal*, so the only thing this can
 * offer is a journal that already exists.
 *
 * The rules asserted here that are not obvious from the component:
 *
 * - The list is populated **before the user types**. A combobox that reveals
 *   nothing until searched would make the common case — "the trip I already
 *   planned for next weekend" — the hardest one.
 * - A **cancelled** future journal is shown and cannot be chosen. It passes
 *   the server's rule, so nothing would refuse it, but a task made due in one
 *   is lapsed the moment it is read back. Hiding it would send the user
 *   hunting for a journal they can see everywhere else.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FutureJournalPicker } from '../FutureJournalPicker';
import { useFutureJournals } from '@/lib/api/journals';
import type { FutureJournalOption } from '@/lib/future-journals';

jest.mock('@/lib/api/journals', () => ({
  useFutureJournals: jest.fn(),
}));

const mockUseFutureJournals = useFutureJournals as jest.MockedFunction<
  typeof useFutureJournals
>;

function option(
  id: string,
  overrides: Partial<FutureJournalOption> = {}
): FutureJournalOption {
  return {
    id,
    title: `Journal ${id}`,
    date: '2026-09-01',
    startsAt: '2026-09-01T12:00:00Z',
    cancelled: false,
    ...overrides,
  };
}

type PickerQueryResult = ReturnType<typeof useFutureJournals>;

function queryResult(
  overrides: Partial<{
    data: FutureJournalOption[] | undefined;
    isLoading: boolean;
    isError: boolean;
  }> = {}
): PickerQueryResult {
  return {
    data: overrides.data ?? [],
    isLoading: overrides.isLoading ?? false,
    isError: overrides.isError ?? false,
  } as PickerQueryResult;
}

function renderPicker(
  props: Partial<React.ComponentProps<typeof FutureJournalPicker>> = {}
) {
  const onSelect = jest.fn();
  const view = render(
    <FutureJournalPicker value={null} onSelect={onSelect} {...props} />
  );
  return { onSelect, ...view };
}

describe('FutureJournalPicker', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseFutureJournals.mockReturnValue(queryResult());
  });

  describe('the list', () => {
    it('shows future journals before the user has typed anything', () => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({
          data: [
            option('1', { title: 'Kanangra trip', date: '2026-08-30' }),
            option('2', { title: 'Team offsite', date: '2026-09-10' }),
          ],
        })
      );

      renderPicker();

      expect(mockUseFutureJournals).toHaveBeenCalledWith(
        expect.objectContaining({ search: '' })
      );
      expect(screen.getAllByRole('option')).toHaveLength(2);
    });

    /**
     * The hook answers nearest-first; the picker must not re-sort what the
     * hook has already decided, or two definitions of the order exist.
     */
    it('renders the options in the order it is given them', () => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({
          data: [
            option('near', { title: 'Nearest', date: '2026-08-30' }),
            option('far', { title: 'Furthest', date: '2026-12-01' }),
          ],
        })
      );

      renderPicker();

      const options = screen.getAllByRole('option');
      expect(options[0]).toHaveTextContent('Nearest');
      expect(options[1]).toHaveTextContent('Furthest');
    });

    it('shows each journal’s date beside its title', () => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({ data: [option('1', { date: '2026-09-01' })] })
      );

      renderPicker();

      expect(screen.getByRole('option')).toHaveTextContent('1 Sep 2026');
    });

    it('announces how many journals are on offer', () => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({ data: [option('1'), option('2')] })
      );

      renderPicker();

      const status = screen.getByRole('status');
      expect(status).toHaveTextContent('2');
      expect(status).toHaveAttribute('aria-live', 'polite');
    });
  });

  describe('searching', () => {
    it('searches future journals once the typing settles', async () => {
      const user = userEvent.setup();
      renderPicker();

      await user.type(screen.getByRole('combobox'), 'kanangra');

      await waitFor(() =>
        expect(mockUseFutureJournals).toHaveBeenCalledWith(
          expect.objectContaining({ search: 'kanangra' })
        )
      );
    });

    it('does not issue a search for every keystroke', async () => {
      const user = userEvent.setup();
      renderPicker();

      await user.type(screen.getByRole('combobox'), 'kan');

      const searched = mockUseFutureJournals.mock.calls
        .map(([args]) => args?.search)
        .filter(search => search === 'k' || search === 'ka');
      expect(searched).toEqual([]);
    });
  });

  describe('empty and unavailable states', () => {
    it('says the window is empty rather than showing an empty box', () => {
      renderPicker();

      expect(screen.getByTestId('future-journal-empty')).toHaveTextContent(
        /90 days/i
      );
      expect(screen.queryAllByRole('option')).toHaveLength(0);
    });

    it('says nothing matched when a search comes back empty', async () => {
      const user = userEvent.setup();
      renderPicker();

      await user.type(screen.getByRole('combobox'), 'nothing');

      await waitFor(() =>
        expect(screen.getByTestId('future-journal-empty')).toHaveTextContent(
          /no future journals match/i
        )
      );
    });

    it('reports a failed listing rather than reading as “no journals”', () => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({ isError: true, data: undefined })
      );

      renderPicker();

      expect(screen.getByTestId('future-journal-error')).toBeInTheDocument();
      expect(screen.queryByTestId('future-journal-empty')).toBeNull();
    });

    /**
     * `keepPreviousData` holds the previous key's `data` across a search, so a
     * failed refetch arrives with `data` populated *and* `isError` set. Without
     * the guard the picker would say the journals could not be loaded while
     * still offering a usable list from a search the user had moved on from.
     */
    it('offers nothing from a failed read, even when a previous list is cached', async () => {
      const user = userEvent.setup();
      mockUseFutureJournals.mockReturnValue(
        queryResult({ isError: true, data: [option('1'), option('2')] })
      );

      const { onSelect } = renderPicker();

      expect(screen.getByTestId('future-journal-error')).toBeInTheDocument();
      expect(screen.queryAllByRole('option')).toHaveLength(0);
      expect(screen.getByRole('combobox')).toHaveAttribute(
        'aria-expanded',
        'false'
      );

      await user.click(screen.getByRole('combobox'));
      await user.keyboard('{ArrowDown}{Enter}');
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('shows a loading line rather than an empty state while it loads', () => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({ isLoading: true, data: undefined })
      );

      renderPicker();

      expect(screen.getByTestId('future-journal-loading')).toBeInTheDocument();
      expect(screen.queryByTestId('future-journal-empty')).toBeNull();
    });
  });

  describe('choosing', () => {
    it('reports the chosen journal to its caller', async () => {
      const user = userEvent.setup();
      const chosen = option('7', { title: 'Kanangra trip' });
      mockUseFutureJournals.mockReturnValue(queryResult({ data: [chosen] }));

      const { onSelect } = renderPicker();
      await user.click(screen.getByRole('option'));

      expect(onSelect).toHaveBeenCalledWith(chosen);
    });

    it('marks the current value as the selected option', () => {
      const chosen = option('7');
      mockUseFutureJournals.mockReturnValue(
        queryResult({ data: [chosen, option('8')] })
      );

      renderPicker({ value: chosen });

      const options = screen.getAllByRole('option');
      expect(options[0]).toHaveAttribute('aria-selected', 'true');
      expect(options[1]).toHaveAttribute('aria-selected', 'false');
    });
  });

  describe('cancelled journals', () => {
    const cancelled = option('9', {
      title: 'Cancelled standup',
      cancelled: true,
    });

    it('shows a cancelled journal rather than hiding it', () => {
      mockUseFutureJournals.mockReturnValue(queryResult({ data: [cancelled] }));

      renderPicker();

      expect(screen.getByRole('option')).toHaveTextContent(/cancelled/i);
    });

    /**
     * It passes the server's rule — only the date is checked — so nothing
     * would refuse it. The refusal has to be here, because the consequence is
     * a task that is lapsed the moment it is read back.
     */
    it('does not let a cancelled journal be chosen', async () => {
      const user = userEvent.setup();
      mockUseFutureJournals.mockReturnValue(queryResult({ data: [cancelled] }));

      const { onSelect } = renderPicker();
      await user.click(screen.getByRole('option'));

      expect(onSelect).not.toHaveBeenCalled();
      expect(screen.getByRole('option')).toHaveAttribute(
        'aria-disabled',
        'true'
      );
    });

    it('marks the chosen option with a glyph, not only a background', () => {
      const chosen = option('7');
      mockUseFutureJournals.mockReturnValue(queryResult({ data: [chosen] }));

      const { container } = renderPicker({ value: chosen });

      expect(container.querySelector('.lucide-check')).toBeInTheDocument();
    });

    it('says why it cannot be chosen', () => {
      mockUseFutureJournals.mockReturnValue(queryResult({ data: [cancelled] }));

      renderPicker();

      expect(
        within(screen.getByRole('option')).getByText(/lapse/i)
      ).toBeInTheDocument();
    });
  });

  /**
   * The service treats a retarget naming the journal a task is already due in
   * as a **no-op**: nothing is validated, nothing is written, and no reopen
   * acknowledgement is asked for. A *done* task offered its own due journal
   * would therefore answer 200, stay done, and skip the confirmation the
   * specification requires — so the refusal has to be here.
   */
  describe('the journal the task is already due in', () => {
    const current = option('5', { title: 'Weekly review' });

    it('is shown, marked and not selectable', async () => {
      const user = userEvent.setup();
      mockUseFutureJournals.mockReturnValue(queryResult({ data: [current] }));

      const { onSelect } = renderPicker({ currentDueJournalId: '5' });
      const shown = screen.getByRole('option');
      expect(shown).toHaveTextContent(/already due here/i);
      expect(shown).toHaveAttribute('aria-disabled', 'true');

      await user.click(shown);
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('cannot be taken with the keyboard either', async () => {
      const user = userEvent.setup();
      mockUseFutureJournals.mockReturnValue(queryResult({ data: [current] }));

      const { onSelect } = renderPicker({ currentDueJournalId: '5' });
      await user.click(screen.getByRole('combobox'));
      await user.keyboard('{ArrowDown}{Enter}');

      expect(onSelect).not.toHaveBeenCalled();
    });

    it('leaves every other journal selectable', async () => {
      const user = userEvent.setup();
      mockUseFutureJournals.mockReturnValue(
        queryResult({ data: [current, option('6')] })
      );

      const { onSelect } = renderPicker({ currentDueJournalId: '5' });
      await user.click(screen.getByTestId('future-journal-option-6'));

      expect(onSelect).toHaveBeenCalledWith(
        expect.objectContaining({ id: '6' })
      );
    });
  });

  describe('when the whole control is disabled', () => {
    it('takes no selection from a click', async () => {
      const user = userEvent.setup();
      mockUseFutureJournals.mockReturnValue(
        queryResult({ data: [option('1')] })
      );

      const { onSelect } = renderPicker({ disabled: true });
      await user.click(screen.getByRole('option'));

      expect(onSelect).not.toHaveBeenCalled();
      expect(screen.getByRole('combobox')).toBeDisabled();
    });
  });

  describe('keyboard operation', () => {
    beforeEach(() => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({
          data: [
            option('1', { title: 'First' }),
            option('2', { title: 'Second' }),
          ],
        })
      );
    });

    it('moves the active option with the arrow keys', async () => {
      const user = userEvent.setup();
      renderPicker();

      const input = screen.getByRole('combobox');
      await user.click(input);
      await user.keyboard('{ArrowDown}');
      expect(input).toHaveAttribute(
        'aria-activedescendant',
        screen.getAllByRole('option')[0].id
      );

      await user.keyboard('{ArrowDown}');
      expect(input).toHaveAttribute(
        'aria-activedescendant',
        screen.getAllByRole('option')[1].id
      );

      await user.keyboard('{ArrowUp}');
      expect(input).toHaveAttribute(
        'aria-activedescendant',
        screen.getAllByRole('option')[0].id
      );
    });

    it('chooses the active option with Enter', async () => {
      const user = userEvent.setup();
      const { onSelect } = renderPicker();

      await user.click(screen.getByRole('combobox'));
      await user.keyboard('{ArrowDown}{Enter}');

      expect(onSelect).toHaveBeenCalledWith(
        expect.objectContaining({ id: '1' })
      );
    });

    /**
     * Enter with nothing active must not submit the form the picker sits in:
     * a dialog whose Enter key sometimes picks a journal and sometimes sends
     * the request is a dialog nobody can use confidently.
     */
    it('does not choose anything when Enter is pressed with no active option', async () => {
      const user = userEvent.setup();
      const { onSelect } = renderPicker();

      await user.click(screen.getByRole('combobox'));
      await user.keyboard('{Enter}');

      expect(onSelect).not.toHaveBeenCalled();
    });

    /**
     * The list is part of the dialog rather than a popover over it, so there
     * is nothing for Escape to close here — and swallowing it would strand a
     * keyboard user inside a dialog whose usual way out had stopped working.
     */
    it('leaves Escape to the dialog it sits in', async () => {
      const user = userEvent.setup();
      const onEscape = jest.fn();
      render(
        // eslint-disable-next-line jsx-a11y/no-static-element-interactions
        <div onKeyDown={onEscape}>
          <FutureJournalPicker value={null} onSelect={jest.fn()} />
        </div>
      );

      await user.click(screen.getByRole('combobox'));
      await user.keyboard('{Escape}');

      expect(onEscape).toHaveBeenCalled();
    });

    it('lands on a cancelled option but refuses to choose it', async () => {
      const user = userEvent.setup();
      mockUseFutureJournals.mockReturnValue(
        queryResult({
          data: [option('9', { title: 'Cancelled', cancelled: true })],
        })
      );

      const { onSelect } = renderPicker();
      await user.click(screen.getByRole('combobox'));
      await user.keyboard('{ArrowDown}');

      expect(screen.getByRole('combobox')).toHaveAttribute(
        'aria-activedescendant',
        screen.getByRole('option').id
      );

      await user.keyboard('{Enter}');
      expect(onSelect).not.toHaveBeenCalled();
    });
  });

  describe('accessibility', () => {
    beforeEach(() => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({ data: [option('1')] })
      );
    });

    it('is a combobox controlling a named listbox', () => {
      renderPicker();

      const input = screen.getByRole('combobox');
      const listbox = screen.getByRole('listbox');
      expect(input).toHaveAttribute('aria-expanded', 'true');
      expect(input).toHaveAttribute('aria-controls', listbox.id);
      expect(listbox).toHaveAccessibleName();
    });

    /**
     * The listbox is hidden while it holds nothing, so a combobox still
     * claiming to be expanded would be pointing assistive technology at an
     * element that is not displayed.
     */
    it.each([
      ['there is nothing to show', { data: [] }],
      ['the listing is still loading', { isLoading: true, data: undefined }],
      ['the listing failed', { isError: true, data: undefined }],
    ])('reports itself collapsed when %s', (_, state) => {
      mockUseFutureJournals.mockReturnValue(queryResult(state));

      renderPicker();

      expect(screen.getByRole('combobox')).toHaveAttribute(
        'aria-expanded',
        'false'
      );
    });

    it('reports itself invalid when the field it serves is', () => {
      renderPicker({ invalid: true });

      expect(screen.getByRole('combobox')).toHaveAttribute(
        'aria-invalid',
        'true'
      );
    });

    it('takes the id and description the form field gives it', () => {
      renderPicker({
        inputId: 'due-journal',
        describedById: 'due-journal-msg',
      });

      const input = screen.getByRole('combobox');
      expect(input).toHaveAttribute('id', 'due-journal');
      expect(input.getAttribute('aria-describedby')).toContain(
        'due-journal-msg'
      );
    });

    /**
     * The listing endpoint's `search` filter is
     * `(j.title ILIKE :search OR j.content ILIKE :search)` — it does not touch
     * either event-date column, so a date query cannot match. The control must
     * not advertise otherwise.
     */
    it('does not promise a search the endpoint cannot do', () => {
      renderPicker();

      const placeholder =
        screen.getByRole('combobox').getAttribute('placeholder') ?? '';
      expect(placeholder).toMatch(/title/i);
      expect(placeholder).not.toMatch(/date/i);
    });

    it('says the same thing in the empty state', () => {
      // This block's `beforeEach` supplies an option; the empty state needs none.
      mockUseFutureJournals.mockReturnValue(queryResult({ data: [] }));

      renderPicker();

      const empty =
        screen.getByTestId('future-journal-empty').textContent ?? '';
      expect(empty).toMatch(/search by title/i);
      expect(empty).not.toMatch(/by title or date/i);
    });

    /**
     * The fifth invariant, asserted where a reviewer would look for it: the
     * product must not offer a bare date picker, so this component must not
     * grow one.
     */
    it('offers no date input of any kind', () => {
      const { container } = renderPicker();

      expect(container.querySelector('input[type="date"]')).toBeNull();
      expect(
        container.querySelector('input[type="datetime-local"]')
      ).toBeNull();
    });
  });

  /**
   * The specification's *"if the user has no future journals, the product
   * should say so plainly and offer to create one, rather than presenting an
   * empty picker"*.
   *
   * The offer lives here rather than in the dialogs above it, so that both the
   * create form and the retarget dialog get it — the retarget dialog's empty
   * state was a dead end until this landed.
   *
   * It appears only where it is the honest answer: with nothing in the window
   * and no search narrowing it. A search that matched nothing says something
   * about the search, and a listing that failed or has not arrived says
   * nothing about what the user has at all.
   */
  describe('the offer to create a journal', () => {
    const offer = () => screen.queryByTestId('future-journal-create-offer');

    it('offers to create a journal when there is nothing to choose from', () => {
      renderPicker();

      const link = offer();
      expect(link).toBeInTheDocument();
      expect(link).toHaveAttribute('href', '/journals/new');
      expect(link).toHaveAccessibleName(/create a journal/i);
    });

    /**
     * This picker lives inside dialogs that are mid-write, so following the
     * offer in place would throw away the task being composed and land the
     * user on the new journal with no route back. A new tab leaves the dialog
     * standing, and the app refetches on window focus, so the journal they
     * just made is in this list when they come back to it.
     */
    it('opens the offer in a new tab, and says that it does', () => {
      renderPicker();

      const link = offer();
      expect(link).toHaveAttribute('target', '_blank');
      expect(link?.getAttribute('rel') ?? '').toContain('noopener');
      // Said out loud rather than left as a surprise.
      expect(link).toHaveAccessibleName(/new tab/i);
    });

    it('is not offered while there are journals to choose from', () => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({ data: [option('1'), option('2')] })
      );

      renderPicker();

      expect(offer()).toBeNull();
    });

    it('is not offered when a search is what came back empty', async () => {
      const user = userEvent.setup();
      renderPicker();

      await user.type(screen.getByRole('combobox'), 'nothing');

      await waitFor(() =>
        expect(screen.getByTestId('future-journal-empty')).toHaveTextContent(
          /no future journals match/i
        )
      );
      expect(offer()).toBeNull();
    });

    it('is not offered while the listing is still loading', () => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({ isLoading: true, data: undefined })
      );

      renderPicker();

      expect(offer()).toBeNull();
    });

    it('is not offered when the listing failed', () => {
      mockUseFutureJournals.mockReturnValue(
        queryResult({ isError: true, data: undefined })
      );

      renderPicker();

      expect(offer()).toBeNull();
    });
  });
});
