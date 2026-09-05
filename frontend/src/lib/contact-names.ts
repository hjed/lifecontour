/**
 * Splitting a contact's display name for an avatar's initials.
 *
 * Some read models hand a contact over as a single display name — a task's
 * contacts, an agenda entry's participants — while `ContactAvatar` wants the
 * parts. Everything after the first space is the surname, which is wrong for
 * some names and right for the initials in all of them. Shared so the task row
 * and the agenda row derive the same initials for the same person.
 */
export function nameParts(displayName: string): {
  first: string;
  last: string;
} {
  const [first = '', ...rest] = displayName.trim().split(/\s+/);
  return { first, last: rest.join(' ') };
}
