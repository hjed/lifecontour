/**
 * The create-task form's creating-journal search, for a host with no journal
 * of its own to supply (the New dialog).
 *
 * Any of the user's journals can be where a task arose — past, today, future
 * or cancelled — so this is the all-journals `JournalSearchCombobox` rather
 * than the due field's future-only picker.
 *
 * **What the box shows is owned here**, not derived from the chosen journal.
 * The combobox re-syncs its input whenever its `value` prop changes, so a
 * value computed as `chosen?.title ?? ''` would throw away the keystroke that
 * un-chose a journal (the trap `AttachTaskDialog` documents). The query follows
 * the chosen journal only when a *new* one arrives — picked from the list, or
 * pre-filled by the host — and otherwise holds exactly what was typed.
 */

'use client';

import { useState } from 'react';

import { useFormField } from '@/components/ui/form';
import { JournalSearchCombobox } from '@/components/journals/JournalSearchCombobox';

/** A chosen creating journal: the id the request needs, the title shown. */
export interface ChosenJournal {
  readonly id: string;
  readonly title: string;
}

export interface CreatingJournalFieldProps {
  readonly inputId: string;
  readonly value: ChosenJournal | null;
  /**
   * The choice changed — a journal picked, or `null` on any keystroke that
   * leaves none chosen. Called on every edit, so a host can tell a field the
   * user has worked in from one still holding its default.
   */
  readonly onChange: (journal: ChosenJournal | null) => void;
  readonly disabled: boolean;
}

export function CreatingJournalField({
  inputId,
  value,
  onChange,
  disabled,
}: CreatingJournalFieldProps) {
  const { error, formDescriptionId, formMessageId } = useFormField();
  const [query, setQuery] = useState(value?.title ?? '');
  const [shownId, setShownId] = useState(value?.id ?? null);
  // The last journal the box held, so typing its title back in — after a
  // stray keystroke, say — chooses it again instead of leaving a box that
  // reads like a choice the form does not hold.
  const [lastChosen, setLastChosen] = useState(value);

  // A journal chosen from outside the box — the host's pre-fill — shows its
  // title. Clearing the choice does not empty the box: the clearing was a
  // keystroke, and the box should keep it.
  if (value && value.id !== shownId) {
    setShownId(value.id);
    setQuery(value.title);
    setLastChosen(value);
  }

  // `FormControl` cannot wrap a control that owns its input, so the pairing it
  // would make is made here: the description always, the message when there is
  // one.
  const describedBy = [formDescriptionId, error ? formMessageId : null]
    .filter(Boolean)
    .join(' ');

  return (
    <JournalSearchCombobox
      inputId={inputId}
      placeholder='Search your journals…'
      value={query}
      disabled={disabled}
      invalid={Boolean(error)}
      describedById={describedBy}
      onSelect={journal => {
        const chosen = { id: journal.id, title: journal.attributes.title };
        setShownId(chosen.id);
        setQuery(chosen.title);
        setLastChosen(chosen);
        onChange(chosen);
      }}
      onSearchChange={typed => {
        setQuery(typed);
        if (lastChosen && typed === lastChosen.title) {
          setShownId(lastChosen.id);
          onChange(lastChosen);
          return;
        }
        setShownId(null);
        onChange(null);
      }}
    />
  );
}
