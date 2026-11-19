/**
 * The New dialog's Task panel: a task in a journal.
 *
 * The navigation specification's *A journal* destination "creates a
 * journal-only task under the existing rules, so the dialog asks for the
 * creating journal and the future due journal. No date field is offered." That
 * is `CreateTaskForm` with the creating journal as a choice. What the panel
 * adds is the pre-fill: "the journal being viewed as creating journal.
 * Otherwise the user must choose."
 *
 * The journal being viewed is read from the path (`journalIdFromPath`), and
 * its title from the journal read the page has usually already cached. The
 * dialog's content remounts on every opening, so each opening reads the page
 * it was opened on. A read still in flight when the panel mounts is applied
 * once it lands, by the form, and only to a field the user has not touched.
 *
 * After a create the dialog closes and the user stays where they were: New is
 * quick capture, the toast announces the task, and a journal page on screen
 * refreshes its own tasks. The form already ignores a create that settles
 * after it has gone, so a dialog closed mid-save is not reached for again.
 *
 * *On a list* is the other destination; it arrives as a switch in this panel.
 */

'use client';

import { useMemo } from 'react';
import { usePathname } from 'next/navigation';

import { CreateTaskForm } from '@/components/tasks/CreateTaskForm';
import type { NewEntityPanelProps } from '@/components/layout/new-dialog/types';
import { useJournal } from '@/lib/api/journals';
import { journalIdFromPath } from '@/lib/viewed-journal';

export function NewTaskPanel({
  onCreated,
  onCancel,
  onBusyChange,
  shownOnOpen = false,
}: NewEntityPanelProps) {
  const viewedId = journalIdFromPath(usePathname());
  // Disabled on an empty id, so nothing is read away from a journal page.
  const { data: viewed } = useJournal(viewedId ?? '');

  const loadedId = viewed?.data.id;
  const loadedTitle = viewed?.data.attributes.title;
  // One object per journal, not per render: the form treats a new `initial`
  // as a new pre-fill to consider.
  const initial = useMemo(
    () =>
      loadedId && loadedTitle !== undefined
        ? { id: String(loadedId), title: loadedTitle }
        : undefined,
    [loadedId, loadedTitle]
  );

  return (
    <div className='space-y-4'>
      <p className='text-muted-foreground text-sm'>
        In a journal: recorded where it arose, and due in a journal you have
        planned.
      </p>
      <CreateTaskForm
        creatingJournal={
          initial ? { kind: 'choose', initial } : { kind: 'choose' }
        }
        onCreated={onCreated}
        onCancel={onCancel}
        onBusyChange={onBusyChange}
        autoFocusText={shownOnOpen}
      />
    </div>
  );
}
