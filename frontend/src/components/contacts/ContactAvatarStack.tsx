import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { nameParts } from '@/lib/contact-names';
import { cn } from '@/lib/utils';

const VISIBLE_PEOPLE = 3;

export interface ContactAvatarStackPerson {
  readonly id: number;
  readonly name: string;
  readonly photoUrl?: string | null;
}

export interface ContactAvatarStackNoun {
  readonly one: string;
  readonly many: string;
}

interface ContactAvatarStackProps {
  readonly people: readonly ContactAvatarStackPerson[];
  readonly label: string;
  readonly noun: ContactAvatarStackNoun;
  readonly testId?: string;
}

/**
 * An overlapping stack of avatars, ringed in the background colour, with a
 * muted `+N` past three. The list is named, each avatar is named for its
 * person, and the `+N` names the people it stands in for.
 */
export function ContactAvatarStack({
  people,
  label,
  noun,
  testId,
}: ContactAvatarStackProps) {
  if (people.length === 0) {
    return null;
  }

  const shown = people.slice(0, VISIBLE_PEOPLE);
  const hidden = people.slice(VISIBLE_PEOPLE);

  return (
    <ul aria-label={label} className='flex items-center' data-testid={testId}>
      {shown.map((person, index) => {
        const { first, last } = nameParts(person.name);
        return (
          <li key={person.id} className={cn('flex', index > 0 && '-ml-2')}>
            <ContactAvatar
              firstName={first}
              lastName={last}
              {...(person.photoUrl ? { imageUrl: person.photoUrl } : {})}
              size='sm'
              className='ring-background h-6 w-6 text-[10px] ring-2'
            />
          </li>
        );
      })}
      {hidden.length > 0 && (
        <li
          className='text-muted-foreground ml-1.5 text-xs'
          aria-label={overflowLabel(hidden, noun)}
        >
          +{hidden.length}
        </li>
      )}
    </ul>
  );
}

function overflowLabel(
  hidden: readonly ContactAvatarStackPerson[],
  noun: ContactAvatarStackNoun
): string {
  const word = hidden.length === 1 ? noun.one : noun.many;
  const names = hidden.map(person => person.name).join(', ');
  return `${hidden.length} more ${word}: ${names}`;
}
