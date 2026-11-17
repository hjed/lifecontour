/**
 * Creates a contact from `ContactForm` and opens the new contact's page.
 *
 * Shared by `/contacts/new` and the New dialog, so both create a contact the
 * same way. Navigation and `onCreated` happen only once the create has
 * succeeded, and only while the form is still on screen: a create that
 * settles after the user closed the dialog or left the page does not pull them
 * to the new contact (the mutation's toast still confirms it). On failure the
 * form stays as it is and the mutation's own error toast explains why.
 */

'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';

import { ContactForm } from '@/components/contacts/ContactForm';
import { useCreateContact } from '@/lib/api/contacts';
import type { ContactFormData } from '@/types/contacts';

export interface CreateContactFormProps {
  readonly onCancel: () => void;
  /** Called after a successful create, before navigating to the contact. */
  readonly onCreated?: () => void;
}

export function CreateContactForm({
  onCancel,
  onCreated,
}: CreateContactFormProps) {
  const router = useRouter();
  const createContactMutation = useCreateContact();
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const handleSubmit = async (data: ContactFormData) => {
    try {
      const result = await createContactMutation.mutateAsync(data);
      if (!mounted.current) return;
      onCreated?.();
      router.push(`/contacts/${result.data.id}`);
    } catch (error) {
      // The mutation's onError toast tells the user what went wrong.
      console.error('Failed to create contact:', error);
    }
  };

  return (
    <ContactForm
      onSubmit={handleSubmit}
      onCancel={onCancel}
      isLoading={createContactMutation.isPending}
    />
  );
}
