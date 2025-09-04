/**
 * Enhanced ContactIdentity component with inline editing capabilities.
 *
 * Allows users to edit contact name and nickname directly inline
 * with optimistic updates and proper error handling.
 */

'use client';

import { generateDisplayName } from '@/lib/utils';
import { validateRequired } from '@/lib/validation';
import { useUpdateContactField } from '@/lib/api/contacts';
import { FavouriteToggle } from './FavouriteToggle';
import { InlineEditField } from './InlineEditField';
import type { ContactResource } from '@/types/contacts';

interface ContactIdentityInlineProps {
  readonly contact: ContactResource;
  readonly className?: string;
}

/**
 * ContactIdentity component with inline editing for name and nickname fields.
 * Displays the contact's name, nickname, and favourite toggle with click-to-edit functionality.
 */
export function ContactIdentityInline({
  contact,
  className,
}: ContactIdentityInlineProps) {
  const updateFieldMutation = useUpdateContactField();

  const displayName = generateDisplayName(
    contact.attributes.first_name,
    contact.attributes.last_name || ''
  );

  const favouriteProps = {
    contactId: contact.id,
    contactName: displayName,
    isFavourite: contact.attributes.is_favourite || false,
  };

  // Handle field updates
  const handleFirstNameSave = async (value: string) => {
    await updateFieldMutation.mutateAsync({
      contactId: contact.id,
      fieldName: 'first_name',
      value,
    });
  };

  const handleLastNameSave = async (value: string) => {
    await updateFieldMutation.mutateAsync({
      contactId: contact.id,
      fieldName: 'last_name',
      value,
    });
  };

  const handleNicknameSave = async (value: string) => {
    await updateFieldMutation.mutateAsync({
      contactId: contact.id,
      fieldName: 'nick_name',
      value,
    });
  };

  return (
    <div className={className}>
      <div className='mb-2 flex flex-col gap-2'>
        {/* Name Fields */}
        <div className='flex flex-wrap items-center gap-2'>
          <div className='flex items-center gap-1'>
            <InlineEditField
              value={contact.attributes.first_name}
              onSave={handleFirstNameSave}
              validation={validateRequired}
              placeholder='First name'
              className='text-2xl font-bold tracking-tight'
              aria-label='First name'
              data-testid='first-name-field'
            />
            <InlineEditField
              value={contact.attributes.last_name}
              onSave={handleLastNameSave}
              placeholder='Last name'
              className='text-2xl font-bold tracking-tight'
              aria-label='Last name'
              data-testid='last-name-field'
            />
          </div>
          <FavouriteToggle {...favouriteProps} />
        </div>

        {/* Nickname Field */}
        <div className='flex items-center gap-2'>
          <span className='text-muted-foreground text-lg font-medium'>
            &ldquo;
          </span>
          <InlineEditField
            value={contact.attributes.nick_name}
            onSave={handleNicknameSave}
            placeholder='Add nickname'
            className='text-muted-foreground text-lg font-medium italic'
            aria-label='Nickname'
            data-testid='nickname-field'
          />
          <span className='text-muted-foreground text-lg font-medium'>
            &rdquo;
          </span>
        </div>
      </div>
    </div>
  );
}
