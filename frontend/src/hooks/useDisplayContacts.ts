import { useMemo } from 'react';
import { ContactResource } from '@/types/contacts';

/**
 * Transformed contact data for display purposes
 */
export interface DisplayContact {
  id: string;
  name: string;
  is_favourite: boolean;
  primary_email?: string;
  primary_phone?: string;
  tags: any[];
  created_at: string;
  updated_at: string;
}

/**
 * Custom hook to transform contact data for display
 * Eliminates duplicate contact transformation logic across pages
 */
export function useDisplayContacts(contacts: ContactResource[] | undefined): DisplayContact[] {
  return useMemo(() => {
    if (!contacts) return [];
    
    return contacts.map(contact => ({
      id: contact.id,
      name: `${contact.attributes.first_name} ${contact.attributes.last_name || ''}`.trim(),
      is_favourite: contact.attributes.is_favourite || false,
      primary_email: contact.attributes.contact_methods?.find(
        m => m.attributes.method_type === 'email' && m.attributes.is_primary
      )?.attributes.value,
      primary_phone: contact.attributes.contact_methods?.find(
        m => m.attributes.method_type === 'phone' && m.attributes.is_primary
      )?.attributes.value,
      tags: contact.relationships?.tags?.data || [],
      created_at: contact.attributes.created_at,
      updated_at: contact.attributes.updated_at,
    }));
  }, [contacts]);
}
