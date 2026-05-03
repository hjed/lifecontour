/**
 * JournalContactBadge component for displaying and managing contact relationships.
 *
 * Shows contact badges with relationship types. Allows adding/removing contacts
 * and editing relationship types inline.
 */

'use client';

import { useMemo, useState, useEffect } from 'react';
import Link from 'next/link';
import { X, Plus, Pencil } from 'lucide-react';
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Label } from '@/components/ui/label';
import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { ContactSearchCombobox } from '@/components/contacts/ContactSearchCombobox';
import { cn } from '@/lib/utils';
import type { ContactResource } from '@/types/contacts';
import type { JournalContact } from '@/types/journals';
import {
  JournalContactRelationshipType,
  AttendeeStatus,
  ContactEventRole,
} from '@/types/journals';

interface JournalContactBadgeProps {
  readonly contacts: JournalContact[];
  readonly onContactAdd?: (
    contactIds: string[],
    relationshipType: JournalContactRelationshipType,
    status?: AttendeeStatus | null,
    role?: ContactEventRole | null
  ) => Promise<void>;
  readonly onContactRemove?: (contactId: string) => Promise<void>;
  readonly onRelationshipUpdate?: (
    contactId: string,
    relationshipType: JournalContactRelationshipType,
    status?: AttendeeStatus | null,
    role?: ContactEventRole | null
  ) => Promise<void>;
  readonly relationshipTypes?: JournalContactRelationshipType[];
  readonly disabled?: boolean;
  readonly defaultStatus?: AttendeeStatus;
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
  onRelationshipUpdate,
  relationshipTypes = [
    JournalContactRelationshipType.PARTICIPANT,
    JournalContactRelationshipType.INVITEE,
    JournalContactRelationshipType.MENTION,
    JournalContactRelationshipType.ABOUT,
  ],
  defaultStatus,
  disabled = false,
  className,
}: JournalContactBadgeProps) {
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [selectedContacts, setSelectedContacts] = useState<ContactResource[]>(
    []
  );
  const [selectedRelationshipType, setSelectedRelationshipType] =
    useState<JournalContactRelationshipType>(
      JournalContactRelationshipType.PARTICIPANT
    );
  const [selectedStatus, setSelectedStatus] = useState<
    AttendeeStatus | 'NO_STATUS'
  >(defaultStatus || 'NO_STATUS');
  const [selectedRole, setSelectedRole] = useState<
    ContactEventRole | 'NO_ROLE'
  >('NO_ROLE');
  const [isLoading, setIsLoading] = useState(false);

  // Reset form when opened
  useEffect(() => {
    if (isAddOpen) {
      setSelectedContacts([]);
      setSelectedRelationshipType(JournalContactRelationshipType.PARTICIPANT);
      setSelectedStatus(defaultStatus || 'NO_STATUS');
      setSelectedRole('NO_ROLE');
    }
  }, [isAddOpen, defaultStatus]);

  const existingContactIds = useMemo(() => contacts.map(c => c.id), [contacts]);
  const excludeContactIds = useMemo(
    () => [...existingContactIds, ...selectedContacts.map(c => c.id)],
    [existingContactIds, selectedContacts]
  );

  const handleAddContact = async () => {
    if (!onContactAdd || selectedContacts.length === 0) {
      return;
    }

    setIsLoading(true);
    try {
      const isEventRole =
        selectedRelationshipType ===
          JournalContactRelationshipType.PARTICIPANT ||
        selectedRelationshipType === JournalContactRelationshipType.INVITEE;
      const resolvedStatus = isEventRole
        ? selectedStatus === 'NO_STATUS'
          ? null
          : selectedStatus
        : null;
      const resolvedRole = isEventRole
        ? selectedRole === 'NO_ROLE'
          ? null
          : selectedRole
        : null;
      await onContactAdd(
        selectedContacts.map(c => c.id),
        selectedRelationshipType,
        resolvedStatus,
        resolvedRole
      );
      setIsAddOpen(false);
    } catch (error) {
      console.error('Failed to add contacts:', error);
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

  const handleUpdateContact = async (
    contactId: string,
    relationshipType: JournalContactRelationshipType,
    status?: AttendeeStatus | null,
    role?: ContactEventRole | null
  ) => {
    if (!onRelationshipUpdate) return;
    setIsLoading(true);
    try {
      await onRelationshipUpdate(contactId, relationshipType, status, role);
    } catch (error) {
      console.error('Failed to update contact:', error);
      throw error;
    } finally {
      setIsLoading(false);
    }
  };

  const canEdit =
    !disabled && (onContactAdd || onContactRemove || onRelationshipUpdate);

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
          onUpdate={
            onRelationshipUpdate
              ? (status, role) =>
                  handleUpdateContact(
                    contact.id,
                    contact.relationship_type,
                    status,
                    role
                  )
              : undefined
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
                <Label htmlFor='journal-contact-search'>Select Contacts</Label>
                <div className='mb-2 flex flex-wrap gap-1'>
                  {selectedContacts.map(contact => {
                    const fallbackDisplayName =
                      [
                        contact.attributes.first_name,
                        contact.attributes.last_name,
                      ]
                        .filter(Boolean)
                        .join(' ')
                        .trim() || `Contact ${contact.id}`;
                    return (
                      <Badge
                        key={contact.id}
                        variant='secondary'
                        className='text-xs'
                      >
                        {fallbackDisplayName}
                        <button
                          type='button'
                          className='hover:text-destructive ml-1'
                          aria-label={`Remove ${fallbackDisplayName}`}
                          disabled={disabled || isLoading}
                          onClick={() =>
                            setSelectedContacts(prev =>
                              prev.filter(c => c.id !== contact.id)
                            )
                          }
                        >
                          <X className='h-3 w-3' />
                        </button>
                      </Badge>
                    );
                  })}
                </div>
                <ContactSearchCombobox
                  onSelect={contact =>
                    setSelectedContacts(prev => {
                      if (prev.some(c => c.id === contact.id)) return prev;
                      return [...prev, contact];
                    })
                  }
                  placeholder='Search for a contact...'
                  inputId='journal-contact-search'
                  disabled={disabled || isLoading}
                  excludeContactIds={excludeContactIds}
                />
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
                  disabled={disabled || isLoading}
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

              <div className='space-y-2'>
                <Label className='text-sm font-medium'>Status</Label>
                <Select
                  value={selectedStatus}
                  onValueChange={v =>
                    setSelectedStatus(v as AttendeeStatus | 'NO_STATUS')
                  }
                  disabled={disabled || isLoading}
                >
                  <SelectTrigger className='h-9'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='NO_STATUS'>None</SelectItem>
                    {Object.values(AttendeeStatus).map(s => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className='space-y-2'>
                <Label className='text-sm font-medium'>Role</Label>
                <Select
                  value={selectedRole}
                  onValueChange={v =>
                    setSelectedRole(v as ContactEventRole | 'NO_ROLE')
                  }
                  disabled={disabled || isLoading}
                >
                  <SelectTrigger className='h-9'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='NO_ROLE'>None</SelectItem>
                    {Object.values(ContactEventRole).map(r => (
                      <SelectItem key={r} value={r}>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Button
                onClick={handleAddContact}
                disabled={
                  disabled || selectedContacts.length === 0 || isLoading
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
  readonly onUpdate?: (
    status?: AttendeeStatus | null,
    role?: ContactEventRole | null
  ) => Promise<void>;
  readonly disabled: boolean;
}

function ContactBadge({
  contact,
  onRemove,
  onUpdate,
  disabled,
}: ContactBadgeProps) {
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [editStatus, setEditStatus] = useState<AttendeeStatus | 'NO_STATUS'>(
    contact.status || 'NO_STATUS'
  );
  const [editRole, setEditRole] = useState<ContactEventRole | 'NO_ROLE'>(
    contact.role || 'NO_ROLE'
  );

  const fallbackDisplayName = contact.name?.trim() || `Contact ${contact.id}`;
  const nameParts = fallbackDisplayName.split(/\s+/);
  const firstName = contact.first_name ?? nameParts[0] ?? '';
  const lastName = contact.last_name ?? nameParts.slice(1).join(' ');

  const getStatusColor = (status: AttendeeStatus) => {
    switch (status) {
      case AttendeeStatus.ATTENDING:
      case AttendeeStatus.ATTENDED:
        return 'bg-green-500';
      case AttendeeStatus.MAYBE:
        return 'bg-amber-500';
      case AttendeeStatus.DECLINED:
        return 'bg-red-500 line-through';
      case AttendeeStatus.NO_REPLY:
        return 'bg-neutral-400';
      default:
        return 'bg-neutral-400';
    }
  };

  const isParticipantOrInvitee =
    contact.relationship_type === JournalContactRelationshipType.PARTICIPANT ||
    contact.relationship_type === JournalContactRelationshipType.INVITEE;

  const handleSave = async () => {
    if (!onUpdate) return;
    const resolvedStatus = editStatus === 'NO_STATUS' ? null : editStatus;
    const resolvedRole = editRole === 'NO_ROLE' ? null : editRole;
    try {
      await onUpdate(resolvedStatus, resolvedRole);
      setIsEditOpen(false);
    } catch {
      // Error is logged/handled by onUpdate, keep popover open
    }
  };

  return (
    <Badge
      variant='secondary'
      className={cn(
        'gap-1.5 py-0.5 pr-1 pl-1 text-xs',
        contact.status === AttendeeStatus.DECLINED && 'opacity-60'
      )}
      data-testid={`contact-badge-${contact.id}`}
    >
      <Link
        href={`/contacts/${contact.id}`}
        className={cn(
          'decoration-muted-foreground/50 focus-visible:ring-ring flex items-center gap-1.5 rounded-sm underline-offset-2 hover:underline focus-visible:ring-1 focus-visible:outline-none',
          contact.status === AttendeeStatus.DECLINED && 'line-through'
        )}
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

      {/* Role Badge inside the main Contact Badge */}
      {contact.role && (
        <span
          className='bg-primary/10 text-primary rounded px-1 py-0.5 text-[9px] font-semibold tracking-wider'
          aria-label={`Role: ${contact.role}`}
          data-testid={`contact-role-${contact.id}`}
        >
          {contact.role === ContactEventRole.ORGANISER ? 'ORG' : 'HELP'}
        </span>
      )}

      {contact.status && (
        <TooltipProvider>
          <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
              <span
                className={cn(
                  'ml-0.5 h-2 w-2 rounded-full',
                  getStatusColor(contact.status)
                )}
                aria-label={`Status: ${contact.status}`}
                data-testid={`contact-status-${contact.id}`}
              />
            </TooltipTrigger>
            <TooltipContent>
              <p className='text-xs'>{contact.status}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}

      {onUpdate && isParticipantOrInvitee && (
        <Popover open={isEditOpen} onOpenChange={setIsEditOpen}>
          <PopoverTrigger asChild>
            <button
              type='button'
              disabled={disabled}
              className='hover:bg-muted ml-0.5 rounded-sm p-0.5 transition-colors'
              aria-label={`Edit ${fallbackDisplayName}`}
              data-testid={`edit-contact-${contact.id}`}
            >
              <Pencil className='h-3 w-3' />
            </button>
          </PopoverTrigger>
          <PopoverContent className='w-64 p-3' align='center'>
            <div className='space-y-3'>
              <div className='space-y-1.5'>
                <Label className='text-xs'>Status</Label>
                <Select
                  value={editStatus}
                  onValueChange={v =>
                    setEditStatus(v as AttendeeStatus | 'NO_STATUS')
                  }
                >
                  <SelectTrigger className='h-7 text-xs'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='NO_STATUS'>None</SelectItem>
                    {Object.values(AttendeeStatus).map(s => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className='space-y-1.5'>
                <Label className='text-xs'>Role</Label>
                <Select
                  value={editRole}
                  onValueChange={v =>
                    setEditRole(v as ContactEventRole | 'NO_ROLE')
                  }
                >
                  <SelectTrigger className='h-7 text-xs'>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value='NO_ROLE'>None</SelectItem>
                    {Object.values(ContactEventRole).map(r => (
                      <SelectItem key={r} value={r}>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Button
                size='sm'
                className='h-7 w-full text-xs'
                onClick={handleSave}
                disabled={disabled}
              >
                Save
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      )}

      {onRemove && (
        <button
          type='button'
          onClick={onRemove}
          disabled={disabled}
          className='hover:bg-muted text-muted-foreground hover:text-destructive ml-0.5 rounded-sm p-0.5 transition-colors'
          aria-label={`Remove ${fallbackDisplayName}`}
          data-testid={`remove-contact-${contact.id}`}
        >
          <X className='h-3 w-3' />
        </button>
      )}
    </Badge>
  );
}
