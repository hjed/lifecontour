/**
 * Picks the journal a task is due in — a picker, not a journal browser.
 *
 * A task's due journal must be an **existing** journal dated after today, so
 * the product offers no bare date picker anywhere and never creates a journal
 * to hold a task. This is the control that makes that constraint workable:
 * "recent and near-future journals first, with search across future journals
 * by title and date", which is the specification's own description of it.
 *
 * Three decisions worth knowing before changing it:
 *
 * - **The list is populated before the user types**, and the listbox is part
 *   of the dialog rather than a popover over it. The common case is a journal
 *   the user has already planned for next week, and a combobox that reveals
 *   nothing until searched makes that the hardest case rather than the
 *   easiest. Being inline also means Escape belongs to the dialog, where a
 *   keyboard user expects it, rather than being swallowed to close a list.
 * - **A cancelled future journal is shown and cannot be chosen.** It satisfies
 *   the server's rule — only the date is checked — so nothing would refuse it,
 *   yet a task made due in one is lapsed the instant it is read back
 *   (`DUE_JOURNAL_CANCELLED`), which for a resurrection means resurrecting
 *   nothing. Hiding it would send the user hunting for a journal they can see
 *   on every other surface, so it is shown, marked, and explained.
 * - **The search is by title, not by date, and the wording says so.** The
 *   specification asks for "search across future journals by title and date",
 *   but the listing endpoint's `search` filter is
 *   `(j.title ILIKE :search OR j.content ILIKE :search)` — it does not touch
 *   either event-date column, so a date query cannot match. Matching dates
 *   against the *loaded* window client-side was considered and rejected: it
 *   would make one control search everything by title and only ninety days by
 *   date, which fails silently at exactly the range a date search is for.
 *   Advertising only what works is the honest half; extending the endpoint is
 *   recorded as a follow-up beside the `sort` parameter it would sit next to.
 * - **An empty window offers to create a journal.** The specification asks
 *   that a user with no future journals be told so plainly *and offered one to
 *   create*, rather than shown an empty picker; without the offer this control
 *   is a dead end for exactly the user who most needs it. It lives here rather
 *   than in the dialogs above so both of them have it, and it appears only
 *   where it is the honest answer — with nothing in the window and no search
 *   narrowing it, because an empty *search* says nothing about the user's
 *   calendar. It opens a new tab so the dialog it sits in survives, which
 *   works as a recovery only because `useFutureJournals` opts out of the
 *   staleness gate on window focus; see the note there.
 * - **`JournalSearchCombobox` was not extended.** It searches *all* journals,
 *   shows nothing until typed into, and has no date filter; the merge dialog
 *   and the parent-journal field depend on all three. Four new branches under
 *   two existing consumers is a worse trade than one narrow component.
 *
 * The ordering and the future-dated filter are not this component's: they
 * belong to `useFutureJournals` and the pure module beneath it, and this
 * renders the answer in the order it is given.
 */

'use client';

import { useId, useState } from 'react';
import Link from 'next/link';
import { CalendarClock, CalendarPlus, Check, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useFormField } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { useDebounce } from '@/hooks/useDebounce';
import { useFutureJournals } from '@/lib/api/journals';
import {
  formatFutureJournalDate,
  FUTURE_WINDOW_DAYS,
} from '@/lib/future-journals';
import type { FutureJournalOption } from '@/lib/future-journals';
import { cn } from '@/lib/utils';

/** Long enough that a typed word is one request, short enough to feel live. */
const SEARCH_DEBOUNCE_MS = 300;

export interface FutureJournalPickerProps {
  /** The journal currently chosen, or `null` while nothing is. */
  readonly value: FutureJournalOption | null;
  /** Called with the journal the user chose. Never called for a cancelled one. */
  readonly onSelect: (journal: FutureJournalOption) => void;
  /** The id the surrounding form field wants on the search input. */
  readonly inputId?: string;
  /** The id of the message the surrounding form field wants announced. */
  readonly describedById?: string;
  /** Whether the field this serves is currently in error. */
  readonly invalid?: boolean;
  readonly disabled?: boolean;
  /**
   * The journal the task is **already** due in, when there is one.
   *
   * Offered, marked and unselectable, for a reason the server cannot supply:
   * `retarget_due_journal` treats a request naming the journal a task is
   * already due in as a **no-op** — it validates nothing, writes nothing, and
   * asks for no reopen acknowledgement. So a *done* task retargeted onto its
   * own due journal answers 200 and stays done, and a UI that offered it would
   * report a move that never happened while skipping the confirmation the
   * specification requires.
   */
  readonly currentDueJournalId?: string;
}

function countWording(count: number): string {
  if (count === 0) return 'No future journals to choose from';
  return count === 1 ? '1 future journal' : `${count} future journals`;
}

/** Why an offered journal cannot be chosen, or `null` when it can. */
function refusalFor(
  journal: FutureJournalOption,
  currentDueJournalId: string | undefined
): string | null {
  if (journal.cancelled) {
    return 'Cancelled — a task due here would lapse at once';
  }
  if (journal.id === currentDueJournalId) {
    return 'This task is already due here';
  }
  return null;
}

export function FutureJournalPicker({
  value,
  onSelect,
  inputId,
  describedById,
  invalid = false,
  disabled = false,
  currentDueJournalId,
}: FutureJournalPickerProps) {
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(-1);
  const search = useDebounce(query, SEARCH_DEBOUNCE_MS);

  const generatedId = useId();
  const searchInputId = inputId ?? `${generatedId}-search`;
  const listboxId = `${generatedId}-listbox`;
  const hintId = `${generatedId}-hint`;
  const optionId = (index: number) => `${generatedId}-option-${index}`;

  const { data, isLoading, isError } = useFutureJournals({ search });

  // A failed read offers nothing, rather than the last list that worked.
  // `keepPreviousData` deliberately holds the previous key's `data` across a
  // search, so on a failed refetch `data` is populated *and* `isError` is set —
  // without this the picker would say the journals could not be loaded while
  // still offering a usable list from a search the user has moved on from, with
  // `aria-expanded` claiming a listbox that contradicts the message beside it.
  const options = isError ? [] : (data ?? []);

  // Clamped on read rather than reset in an effect: the list changes with
  // every search, and an index left pointing past its end is a render-time
  // fact, not something worth a second render to correct.
  const active =
    activeIndex >= 0 && activeIndex < options.length ? activeIndex : -1;

  const choose = (journal: FutureJournalOption) => {
    // A refused journal is offered so it can be seen and explained, never so it
    // can be chosen — and the guard is here rather than only on the option,
    // because the keyboard reaches this by a different route.
    if (disabled || refusalFor(journal, currentDueJournalId)) return;
    onSelect(journal);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (options.length === 0) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex(current =>
        current < options.length - 1 ? current + 1 : 0
      );
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex(current =>
        current > 0 ? current - 1 : options.length - 1
      );
      return;
    }

    // Enter with an option under the cursor chooses it and stops there; with
    // nothing active it is left alone, so the dialog's own submit still works
    // the way every other form in the app does.
    if (event.key === 'Enter' && active >= 0) {
      event.preventDefault();
      choose(options[active]);
    }
  };

  const describedBy = [hintId, describedById].filter(Boolean).join(' ');

  return (
    <div className='space-y-2' data-testid='future-journal-picker'>
      <div className='relative'>
        <Search
          aria-hidden='true'
          className='text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2'
        />
        <Input
          id={searchInputId}
          type='text'
          role='combobox'
          autoComplete='off'
          className='pl-10'
          placeholder='Search your future journals by title'
          value={query}
          disabled={disabled}
          onChange={event => {
            setQuery(event.target.value);
            setActiveIndex(-1);
          }}
          onKeyDown={handleKeyDown}
          aria-expanded={options.length > 0}
          aria-controls={listboxId}
          aria-autocomplete='list'
          aria-activedescendant={active >= 0 ? optionId(active) : undefined}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          data-testid='future-journal-search'
        />
      </div>

      <p id={hintId} className='text-muted-foreground text-xs'>
        A task is due in a journal, so only journals dated after today can hold
        one.
      </p>

      {isLoading && (
        <p
          className='text-muted-foreground py-3 text-sm'
          data-testid='future-journal-loading'
        >
          Loading your journals…
        </p>
      )}

      {!isLoading && isError && (
        <p
          className='text-destructive py-3 text-sm'
          data-testid='future-journal-error'
        >
          Your journals could not be loaded, so there is nothing to choose from.
          Try again in a moment.
        </p>
      )}

      {!isLoading && !isError && options.length === 0 && (
        <div className='py-3'>
          <p
            className='text-muted-foreground text-sm'
            data-testid='future-journal-empty'
          >
            {search
              ? `No future journals match “${search}”.`
              : `No journals dated in the next ${FUTURE_WINDOW_DAYS} days. Search by title to find a later one — or, if you have nothing ahead of you at all, create the journal this task belongs to first.`}
          </p>
          {/* The specification's "say so plainly **and offer to create one**".
              Offered only where it is the honest answer: with nothing in the
              window and no search narrowing it. A search that matched nothing
              says something about the search rather than about the user's
              calendar, and sending them off to create a journal there would be
              answering a question they did not ask.

              **It opens in a new tab, and that is the whole point of it.** This
              control lives inside dialogs that are mid-write: a task being
              composed, or a lapsed one being resurrected. Navigating away in
              place would throw that away — the text typed, the contacts chosen
              — and land the user on the *new* journal rather than back on the
              one they were writing in, with no route back to finish. In a new
              tab the dialog survives untouched, and `useFutureJournals` asks
              for `refetchOnWindowFocus: 'always'` so the journal they just
              made is in this list when they return. **That `'always'` is
              load-bearing, not belt-and-braces:** the app-wide default
              refetches only *stale* queries and this one is fresh for five
              minutes, so without it a user who did exactly what they were
              asked would come back to the same empty picker. The label says
              the tab opens, because a link that opens one without saying so is
              its own small betrayal. */}
          {!search && (
            <Button
              asChild
              variant='outline'
              size='sm'
              className='mt-3'
              data-testid='future-journal-create-offer'
            >
              <Link href='/journals/new' target='_blank' rel='noopener'>
                <CalendarPlus aria-hidden='true' />
                Create a journal
                <span className='text-muted-foreground text-xs'>
                  (opens a new tab)
                </span>
              </Link>
            </Button>
          )}
        </div>
      )}

      <ul
        id={listboxId}
        role='listbox'
        aria-label='Future journals'
        className='divide-border max-h-60 divide-y overflow-auto rounded-md border empty:hidden'
        data-testid='future-journal-options'
      >
        {options.map((journal, index) => {
          const refusal = refusalFor(journal, currentDueJournalId);
          const isChosen = value?.id === journal.id;

          return (
            /* eslint-disable-next-line jsx-a11y/click-events-have-key-events --
               The APG's combobox pattern puts every key on the input and leaves
               options unfocusable, so a keyboard handler here would be
               unreachable code standing in for the one on the combobox, which
               has its own arrow, Enter and Escape tests. */
            <li
              key={journal.id}
              id={optionId(index)}
              role='option'
              aria-selected={isChosen}
              aria-disabled={refusal ? true : undefined}
              data-testid={`future-journal-option-${journal.id}`}
              className={cn(
                'flex flex-col gap-1 px-3 py-2 text-sm',
                refusal
                  ? 'text-muted-foreground cursor-not-allowed'
                  : 'hover:bg-muted cursor-pointer',
                index === active && 'bg-muted',
                isChosen && 'bg-accent'
              )}
              // Keeps the search input focused, which is what
              // `aria-activedescendant` needs to stay meaningful.
              onMouseDown={event => event.preventDefault()}
              onClick={() => choose(journal)}
            >
              <span className='flex items-center gap-2'>
                {/* The chosen journal is marked by a glyph as well as a
                    background, so the choice is not carried by colour alone
                    (WCAG 1.4.1). */}
                {isChosen ? (
                  <Check
                    aria-hidden='true'
                    className='text-primary h-4 w-4 shrink-0'
                  />
                ) : (
                  <CalendarClock
                    aria-hidden='true'
                    className='text-muted-foreground h-4 w-4 shrink-0'
                  />
                )}
                <span className='flex-1 truncate font-medium'>
                  {journal.title}
                </span>
                <span className='text-muted-foreground shrink-0 text-xs'>
                  {formatFutureJournalDate(journal.date)}
                </span>
              </span>
              {refusal && (
                <span className='text-destructive text-xs'>{refusal}</span>
              )}
            </li>
          );
        })}
      </ul>

      <p
        role='status'
        aria-live='polite'
        className='sr-only'
        data-testid='future-journal-count'
      >
        {countWording(options.length)}
      </p>
    </div>
  );
}

/**
 * The picker wired to the react-hook-form field it serves.
 *
 * **Not wrapped in `FormControl`, and that is why this exists.** `FormControl`
 * clones `id`, `aria-describedby` and `aria-invalid` onto its child's **root**
 * element, which here is the picker's container rather than its input, so the
 * three are passed to the input explicitly instead. Both dialogs that hold a
 * due-journal field need exactly that, and writing it twice is how the two
 * would drift — one of them growing the description id, or the focus target,
 * without the other.
 *
 * The rest of the form standard is followed as written: the surrounding
 * `FormItem`/`FormLabel`/`FormMessage` belong to the caller, and `FormLabel`'s
 * `htmlFor` points at `inputId` so the label still names the input.
 */
export function DueJournalFormField({
  inputId,
  value,
  onSelect,
  disabled,
  currentDueJournalId,
}: {
  readonly inputId: string;
  readonly value: FutureJournalOption | null;
  readonly onSelect: (journal: FutureJournalOption) => void;
  readonly disabled: boolean;
  /** Only a *retarget* has one; a task being created is not due anywhere yet. */
  readonly currentDueJournalId?: string;
}) {
  const { error, formMessageId } = useFormField();

  return (
    <FutureJournalPicker
      inputId={inputId}
      value={value}
      onSelect={onSelect}
      disabled={disabled}
      invalid={Boolean(error)}
      describedById={error ? formMessageId : undefined}
      {...(currentDueJournalId ? { currentDueJournalId } : {})}
    />
  );
}
