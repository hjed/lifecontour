import { ReactNode } from 'react';
import { ContactCard } from '@/components/contacts/ContactCard';
import { DisplayContact } from '@/hooks/useDisplayContacts';

interface ContactListProps {
  readonly contacts: DisplayContact[];
  readonly emptyState?: ReactNode;
}

/**
 * Reusable contact list component
 * Eliminates duplicate contact list rendering logic across pages
 */
export function ContactList({ contacts, emptyState }: ContactListProps) {
  if (contacts.length === 0 && emptyState) {
    return <>{emptyState}</>;
  }

  return (
    <div className='grid gap-4 md:grid-cols-2 lg:grid-cols-3'>
      {contacts.map(contact => (
        <ContactCard key={contact.id} contact={contact} />
      ))}
    </div>
  );
}
