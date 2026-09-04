/**
 * @jest-environment jsdom
 *
 * The agenda entry's participants (**W16**): an overlapping stack of initials
 * with a `+N` counter when it overflows, and nothing at all when the journal
 * has no participants.
 */

import { render, screen, within } from '@testing-library/react';
import { AgendaParticipantStack } from '../AgendaParticipantStack';
import type { HomeDashboardAgendaParticipant } from '@/lib/api/home-dashboard';

function person(id: number, name: string): HomeDashboardAgendaParticipant {
  return { contact_id: id, name };
}

const SAM = person(1, 'Sam Taylor');
const ALEX = person(2, 'Alex Chen');
const PRIYA = person(3, 'Priya Patel');
const JORDAN = person(4, 'Jordan Lee');
const KIM = person(5, 'Kim Nguyen');

describe('AgendaParticipantStack', () => {
  it('renders nothing when there is nobody to show', () => {
    const { container } = render(<AgendaParticipantStack participants={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('is a labelled group of one avatar per participant, named for them', () => {
    render(<AgendaParticipantStack participants={[SAM, ALEX]} />);

    const group = screen.getByRole('group', { name: 'Participants' });
    const avatars = within(group).getAllByRole('img');
    expect(avatars.map(avatar => avatar.getAttribute('aria-label'))).toEqual([
      'Sam Taylor',
      'Alex Chen',
    ]);
    expect(within(group).getByText('ST')).toBeInTheDocument();
    expect(within(group).getByText('AC')).toBeInTheDocument();
    expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
  });

  it('shows three avatars at most', () => {
    render(<AgendaParticipantStack participants={[SAM, ALEX, PRIYA]} />);

    expect(screen.getAllByRole('img')).toHaveLength(3);
    expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
  });

  it('folds the overflow into a +N that still names who is hidden', () => {
    render(
      <AgendaParticipantStack participants={[SAM, ALEX, PRIYA, JORDAN, KIM]} />
    );

    expect(screen.getAllByRole('img')).toHaveLength(3);
    const overflow = screen.getByText('+2');
    expect(overflow).toHaveAccessibleName(
      '2 more participants: Jordan Lee, Kim Nguyen'
    );
  });

  it('words a single hidden participant in the singular', () => {
    render(
      <AgendaParticipantStack participants={[SAM, ALEX, PRIYA, JORDAN]} />
    );

    expect(screen.getByText('+1')).toHaveAccessibleName(
      '1 more participant: Jordan Lee'
    );
  });
});
