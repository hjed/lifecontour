/**
 * JournalContactBadge component for displaying and managing contact relationships.
 *
 * Shows contact badges with relationship types. Allows adding/removing contacts
 * and editing relationship types inline.
 */

'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { X, Plus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { ContactSearchCombobox } from '@/components/contacts/ContactSearchCombobox';
import { cn } from '@/lib/utils';
import type { ContactResource } from '@/types/contacts';
import type { JournalContact } from '@/types/journals';
import { JournalContactRelationshipType } from '@/types/journals';

interface JournalContactBadgeProps {
  readonly contacts: JournalContact[];
  readonly onContactAdd?: (
    contactId: string,
    relationshipType: JournalContactRelationshipType
  ) => Promise<void>;
  readonly onContactRemove?: (contactId: string) => Promise<void>;
  readonly onRelationshipChange?: (
    contactId: string,
    relationshipType: JournalContactRelationshipType
  ) => Promise<void>;
  readonly relationshipTypes?: JournalContactRelationshipType[];
  readonly disabled?: boolean;
  readonly className?: string;
}

/**
 * Contact badge component with inline editing for relationships.
 * Displays contact names with relationship types.
 */
export function JournalContactBadge({
  contacts,
  onContactAdd,
  onContactRemove,
  onRelationshipChange,
  relationshipTypes = [
    JournalContactRelationshipType.PARTICIPANT,
    JournalContactRelationshipType.INVITEE,
    JournalContactRelationshipType.MENTION,
    JournalContactRelationshipType.ABOUT,
  ],
  disabled = false,
  className,
}: JournalContactBadgeProps) {
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [selectedContact, setSelectedContact] =
    useState<ContactResource | null>(null);
  const [selectedRelationshipType, setSelectedRelationshipType] =
    useState<JournalContactRelationshipType>(
      JournalContactRelationshipType.PARTICIPANT
    );
  const [isLoading, setIsLoading] = useState(false);

  const isSelectedContactAlreadyLinked = useMemo(
    () =>
      selectedContact !== null &&
      contacts.some(contact => contact.id === selectedContact.id),
    [contacts, selectedContact]
  );

  const selectedContactName = useMemo(() => {
    if (!selectedContact) return null;

    return [
      selectedContact.attributes.first_name,
      selectedContact.attributes.last_name,
    ]
      .filter(Boolean)
      .join(' ')
      .trim();
  }, [selectedContact]);

  const handleAddContact = async () => {
    if (!onContactAdd || !selectedContact || isSelectedContactAlreadyLinked) {
      return;
    }

    setIsLoading(true);
    try {
      await onContactAdd(selectedContact.id, selectedRelationshipType);
      setIsAddOpen(false);
      setSelectedContact(null);
      setSelectedRelationshipType(JournalContactRelationshipType.PARTICIPANT);
    } catch (error) {
      console.error('Failed to add contact:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemoveContact = async (contactId: string) => {
    if (!onContactRemove) return;

    setIsLoading(true);
    try {
      await onContactRemove(contactId);
    } catch (error) {
      console.error('Failed to remove contact:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const canEdit =
    !disabled && (onContactAdd || onContactRemove || onRelationshipChange);

  return (
    <div
      className={cn('flex flex-wrap items-center gap-2', className)}
      data-testid='contact-badges'
    >
      {/* Existing Contact Badges */}
      {contacts.map(contact => (
        <ContactBadge
          key={contact.id}
          contact={contact}
          onRemove={
            onContactRemove ? () => handleRemoveContact(contact.id) : undefined
          }
          disabled={disabled || isLoading}
        />
      ))}

      {/* Add Contact Button */}
      {canEdit && onContactAdd && (
        <Popover open={isAddOpen} onOpenChange={setIsAddOpen}>
          <PopoverTrigger asChild>
            <Button
              variant='outline'
              size='sm'
              className='h-6 gap-1 text-xs'
              disabled={disabled || isLoading}
              data-testid='add-contact-button'
            >
              <Plus className='h-3 w-3' />
              Add Contact
            </Button>
          </PopoverTrigger>
          <PopoverContent className='w-80 p-3' align='start'>
            <div className='space-y-3'>
              <div className='space-y-2'>
                <Label htmlFor='journal-contact-search'>Select Contact</Label>
                <ContactSearchCombobox
                  onSelect={setSelectedContact}
                  placeholder='Search for a contact...'
                  inputId='journal-contact-search'
                  disabled={isLoading}
                />
                {selectedContactName && (
                  <p className='text-muted-foreground text-xs'>
                    Selected: {selectedContactName}
                  </p>
                )}
                {isSelectedContactAlreadyLinked && (
                  <p className='text-destructive text-xs'>
                    That contact is already linked to this journal.
                  </p>
                )}
              </div>

              <div className='space-y-2'>
                <label
                  htmlFor='relationship-type-select'
                  className='text-sm font-medium'
                >
                  Relationship Type
                </label>
                <Select
                  value={selectedRelationshipType}
                  onValueChange={value =>
                    setSelectedRelationshipType(
                      value as JournalContactRelationshipType
                    )
                  }
                  disabled={isLoading}
                >
                  <SelectTrigger
                    id='relationship-type-select'
                    data-testid='relationship-type-select'
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {relationshipTypes.map(type => (
                      <SelectItem key={type} value={type}>
                        {type}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Button
                onClick={handleAddContact}
                disabled={
                  !selectedContact ||
                  isSelectedContactAlreadyLinked ||
                  isLoading
                }
                className='w-full'
                size='sm'
              >
                Add
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}

// Individual contact badge with edit/remove functionality
interface ContactBadgeProps {
  readonly contact: JournalContact;
  readonly onRemove?: () => void;
  readonly disabled: boolean;
}

function ContactBadge({ contact, onRemove, disabled }: ContactBadgeProps) {
  const fallbackDisplayName = contact.name?.trim() || `Contact ${contact.id}`;
  const nameParts = fallbackDisplayName.split(/\s+/);
  const firstName = contact.first_name ?? nameParts[0] ?? '';
  const lastName = contact.last_name ?? nameParts.slice(1).join(' ');

  return (
    <Badge
      variant='secondary'
      className='gap-1.5 py-0.5 pr-1 pl-1 text-xs'
      data-testid={`contact-badge-${contact.id}`}
    >
      <Link
        href={`/contacts/${contact.id}`}
        className='decoration-muted-foreground/50 focus-visible:ring-ring flex items-center gap-1.5 rounded-sm underline-offset-2 hover:underline focus-visible:ring-1 focus-visible:outline-none'
        aria-label={`View ${fallbackDisplayName}`}
      >
        <ContactAvatar
          firstName={firstName}
          lastName={lastName}
          size='sm'
          className='h-4 w-4'
        />
        <span>{fallbackDisplayName}</span>
        {contact.relationship_type && (
          <span className='text-muted-foreground text-[10px]'>
            ({contact.relationship_type})
          </span>
        )}
      </Link>
      {onRemove && (
        <button
          type='button'
          onClick={onRemove}
          disabled={disabled}
          className='hover:bg-muted ml-1 rounded-sm p-0.5 transition-colors'
          aria-label={`Remove ${fallbackDisplayName}`}
          data-testid={`remove-contact-${contact.id}`}
        >
          <X className='h-3 w-3' />
        </button>
      )}
    </Badge>
  );
}
