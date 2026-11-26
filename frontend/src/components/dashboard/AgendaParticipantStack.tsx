/**
 * AgendaParticipantStack — who is at an agenda entry (**W16**).
 *
 * The stack is the shared `ContactAvatarStack`. The wireframe fixes no cap;
 * the shared stack's cap of three keeps a row to one line at 375 px beside
 * its tags.
 */

import { ContactAvatarStack } from '@/components/contacts/ContactAvatarStack';
import type { HomeDashboardAgendaParticipant } from '@/lib/api/home-dashboard';

const PARTICIPANT_NOUN = { one: 'participant', many: 'participants' } as const;

interface AgendaParticipantStackProps {
  readonly participants: readonly HomeDashboardAgendaParticipant[];
}

export function AgendaParticipantStack({
  participants,
}: AgendaParticipantStackProps) {
  return (
    <ContactAvatarStack
      people={participants.map(({ contact_id, name }) => ({
        id: contact_id,
        name,
      }))}
      label='Participants'
      noun={PARTICIPANT_NOUN}
      testId='agenda-entry-participants'
    />
  );
}
