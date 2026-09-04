/**
 * AgendaParticipantStack — who is at an agenda entry (**W16**).
 *
 * An overlapping stack of initials, ringed in the background colour so each
 * avatar reads over the one before it, with a muted `+N` when there are more
 * than fit. Three is the cap: the wireframe fixes none, and three keeps a row
 * to one line at 375 px beside its tags.
 *
 * Nothing here is decorative for assistive technology. Every drawn avatar is
 * named for its participant (`ContactAvatar` is an `img` with the name as its
 * label), and the `+N` names the people it stands in for, so a screen-reader
 * user hears the whole guest list rather than "plus two".
 */

import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import type { HomeDashboardAgendaParticipant } from '@/lib/api/home-dashboard';
import { nameParts } from '@/lib/contact-names';

/** How many avatars are drawn before the rest fold into `+N`. */
export const VISIBLE_PARTICIPANTS = 3;

interface AgendaParticipantStackProps {
  readonly participants: readonly HomeDashboardAgendaParticipant[];
}

export function AgendaParticipantStack({
  participants,
}: AgendaParticipantStackProps) {
  if (participants.length === 0) {
    return null;
  }

  const shown = participants.slice(0, VISIBLE_PARTICIPANTS);
  const hidden = participants.slice(VISIBLE_PARTICIPANTS);

  return (
    <div
      role='group'
      aria-label='Participants'
      className='flex items-center'
      data-testid='agenda-entry-participants'
    >
      <div className='flex -space-x-2'>
        {shown.map(participant => {
          const { first, last } = nameParts(participant.name);
          return (
            <ContactAvatar
              key={participant.contact_id}
              firstName={first}
              lastName={last}
              size='sm'
              className='ring-background h-6 w-6 text-[10px] ring-2'
            />
          );
        })}
      </div>
      {hidden.length > 0 && (
        <span
          className='text-muted-foreground ml-1.5 text-xs'
          aria-label={overflowLabel(hidden)}
        >
          +{hidden.length}
        </span>
      )}
    </div>
  );
}

function overflowLabel(
  hidden: readonly HomeDashboardAgendaParticipant[]
): string {
  const noun = hidden.length === 1 ? 'participant' : 'participants';
  const names = hidden.map(participant => participant.name).join(', ');
  return `${hidden.length} more ${noun}: ${names}`;
}
