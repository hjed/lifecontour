/**
 * JournalContactBadge component for displaying and managing contact relationships.
 *
 * Shows contact badges with relationship types. Allows adding/removing contacts
 * and editing relationship types inline.
 */

'use client';

import { useState } from 'react';
import { User, X, Plus } from 'lucide-react';
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
import { cn } from '@/lib/utils';
import type { JournalContact } from '@/types/journals';

interface JournalContactBadgeProps {
  readonly contacts: JournalContact[];
  readonly onContactAdd?: (
    contactId: number,
    relationshipType: string
  ) => Promise<void>;
  readonly onContactRemove?: (contactId: number) => Promise<void>;
  readonly onRelationshipChange?: (
    contactId: number,
    relationshipType: string
  ) => Promise<void>;
  readonly availableContacts?: Array<{ id: number; name: string }>;
  readonly relationshipTypes?: string[];
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
  availableContacts = [],
  relationshipTypes = ['MENTIONED', 'PARTICIPANT', 'ORGANIZER', 'RELATED'],
  disabled = false,
  className,
}: JournalContactBadgeProps) {
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [selectedContactId, setSelectedContactId] = useState<number | null>(
    null
  );
  const [selectedRelationshipType, setSelectedRelationshipType] =
    useState<string>('MENTIONED');
  const [isLoading, setIsLoading] = useState(false);

  const handleAddContact = async () => {
    if (!onContactAdd || !selectedContactId) return;

    setIsLoading(true);
    try {
      await onContactAdd(selectedContactId, selectedRelationshipType);
      setIsAddOpen(false);
      setSelectedContactId(null);
      setSelectedRelationshipType('MENTIONED');
    } catch (error) {
      console.error('Failed to add contact:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemoveContact = async (contactId: number) => {
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
                <label className='text-sm font-medium'>Select Contact</label>
                <Select
                  value={selectedContactId?.toString()}
                  onValueChange={value => setSelectedContactId(Number(value))}
                  disabled={isLoading}
                >
                  <SelectTrigger data-testid='contact-select'>
                    <SelectValue placeholder='Choose a contact' />
                  </SelectTrigger>
                  <SelectContent>
                    {availableContacts
                      .filter(
                        c => !contacts.some(existing => existing.id === c.id)
                      )
                      .map(contact => (
                        <SelectItem
                          key={contact.id}
                          value={contact.id.toString()}
                        >
                          {contact.name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>

              <div className='space-y-2'>
                <label className='text-sm font-medium'>Relationship Type</label>
                <Select
                  value={selectedRelationshipType}
                  onValueChange={setSelectedRelationshipType}
                  disabled={isLoading}
                >
                  <SelectTrigger data-testid='relationship-type-select'>
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
                disabled={!selectedContactId || isLoading}
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
  return (
    <Badge
      variant='secondary'
      className='gap-1.5 pr-1 text-xs'
      data-testid={`contact-badge-${contact.id}`}
    >
      <User className='h-3 w-3' />
      <span>{contact.name}</span>
      {contact.relationshipType && (
        <span className='text-muted-foreground text-[10px]'>
          ({contact.relationshipType})
        </span>
      )}
      {onRemove && (
        <button
          type='button'
          onClick={onRemove}
          disabled={disabled}
          className='hover:bg-muted ml-1 rounded-sm p-0.5 transition-colors'
          aria-label={`Remove ${contact.name}`}
          data-testid={`remove-contact-${contact.id}`}
        >
          <X className='h-3 w-3' />
        </button>
      )}
    </Badge>
  );
}
