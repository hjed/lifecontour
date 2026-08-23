/**
 * Removes the mention link between one task and the journal being viewed.
 *
 * The specification allows exactly this and nothing more: "intermediate links
 * can be removed. The creating and due links cannot be removed, only replaced
 * in the case of the due journal." So this control is mounted only where
 * `linkRemovable` says a link in that role may go, and it is the row's
 * *group* that decides — a task holding two roles in one journal is rendered
 * once per group, and the copy under *Mentioned* offers this while the copy
 * under *Due* does not.
 *
 * **No confirmation.** Deletion is gated because it is permanent and takes the
 * task off every journal it is linked to; a mention is one link, and the way
 * back is the attach affordance in the same card. What it borrows from delete
 * is the *presentation* — icon-only, muted, never the destructive variant —
 * because it is still not one of the ordinary status moves.
 *
 * **It stays locked once the write has succeeded, not only while it is in
 * flight.** The row does not leave the listing until the invalidated refetch
 * comes back, which is a round trip after the `DELETE` resolves, and the
 * shared in-flight guard is false again the moment it does. A second press in
 * that window is refused by the service on exactly the shape this affordance
 * exists for — a journal that is *also* an anchor keeps its intermediate link
 * removable, and detaching it twice raises rather than answering idempotently
 * — so the user would see "Journal unlinked successfully" followed by an error
 * naming the anchor, reading as though the removal had failed.
 */

'use client';

import { Unlink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useDetachTaskIntermediateJournal } from '@/lib/api/tasks';

interface DetachMentionButtonProps {
  /** The task whose mention of this journal is being removed. */
  readonly taskId: string;
  /** The journal being viewed — the link's other end. */
  readonly journalId: string;
  /**
   * Whether the row is locked out because a write against this task is already
   * in flight. Computed once by the actions group and passed down, rather than
   * opened as a second subscription saying the same thing.
   */
  readonly disabled: boolean;
}

/**
 * Named for what pressing it does, and for *which* link it removes.
 *
 * "Remove" alone would read as removing the task, which is the neighbouring
 * button and a very different act.
 */
const ACCESSIBLE_NAME = 'Remove mention from this journal';

export function DetachMentionButton({
  taskId,
  journalId,
  disabled,
}: DetachMentionButtonProps) {
  const detach = useDetachTaskIntermediateJournal();

  return (
    <Button
      type='button'
      variant='ghost'
      size='sm'
      aria-label={ACCESSIBLE_NAME}
      title={ACCESSIBLE_NAME}
      disabled={disabled || detach.isSuccess}
      data-testid='journal-task-action-detach'
      className='text-muted-foreground hover:text-foreground'
      onClick={() => {
        detach.mutate({ taskId, journalId });
      }}
    >
      <Unlink aria-hidden='true' />
    </Button>
  );
}
