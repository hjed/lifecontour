import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from 'personal-management-frontend';

/**
 * Destructive confirmation — the pattern used before deleting a journal entry.
 * `open` is forced so the preview photographs the real overlay; autofocus is
 * suppressed so the screenshot has no focus ring on the cancel button.
 */
export function DeleteEntry() {
  return (
    <AlertDialog open>
      <AlertDialogContent onOpenAutoFocus={e => e.preventDefault()}>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this journal entry?</AlertDialogTitle>
          <AlertDialogDescription>
            &ldquo;Morning run along the Yarra&rdquo; from 14 July 2026 will be
            permanently deleted, along with its 3 tags and 12 km activity
            record. Linked contacts are kept. This action cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction className='bg-destructive text-white'>
            Delete entry
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** Non-destructive confirmation: the default action keeps the primary style. */
export function MergeContacts() {
  return (
    <AlertDialog open>
      <AlertDialogContent onOpenAutoFocus={e => e.preventDefault()}>
        <AlertDialogHeader>
          <AlertDialogTitle>Merge these two contacts?</AlertDialogTitle>
          <AlertDialogDescription>
            Priya Raman will absorb Priya R. — 4 journal entries, 2 email
            addresses and the tag &ldquo;Bushwalking&rdquo; move across. The
            duplicate is archived, not deleted, so you can split it again later.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Not now</AlertDialogCancel>
          <AlertDialogAction>Merge contacts</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
