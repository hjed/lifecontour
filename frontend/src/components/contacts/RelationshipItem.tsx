/**
 * RelationshipItem component for displaying and editing individual relationships.
 *
 * Provides inline editing functionality for relationship types with
 * proper validation and error handling. Supports both contact-to-contact
 * and user-targeted relationships.
 */

'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Edit2, Trash2, Check, X, User } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useRelationshipTypes } from '@/lib/api/relationships';
import { validateRequiredRelationshipType } from '@/lib/validation';
import {
  ContactRelationshipResource,
  ContactRelationshipFormData,
  RelationshipType,
} from '@/types/contacts';

interface RelationshipItemProps {
  readonly relationship: ContactRelationshipResource;
  readonly currentContactId: string;
  readonly onUpdate: (data: ContactRelationshipFormData) => void;
  readonly onDelete: () => void;
  readonly disabled?: boolean;
}

export function RelationshipItem({
  relationship,
  currentContactId,
  onUpdate,
  onDelete,
  disabled = false,
}: RelationshipItemProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [selectedType, setSelectedType] = useState(
    relationship.attributes.relationship_type
  );

  const { data: relationshipTypes, isLoading: typesLoading } =
    useRelationshipTypes();

  // Get display name for relationship type
  const getTypeDisplayName = (type: RelationshipType) => {
    const typeData = relationshipTypes?.relationship_types?.find(
      t => t.value === type
    );
    return typeData?.display_name || type;
  };

  const isUserTargeted = relationship.attributes.to_user;

  // Determine the "other" contact's ID for linking
  const otherContactId = isUserTargeted
    ? null
    : relationship.attributes.from_contact_id === Number(currentContactId)
      ? relationship.attributes.to_contact_id
      : relationship.attributes.from_contact_id;

  const contactName = isUserTargeted
    ? 'You'
    : relationship.attributes.to_contact_name;

  const handleEdit = () => {
    setIsEditing(true);
    setSelectedType(relationship.attributes.relationship_type);
  };

  const handleCancel = () => {
    setIsEditing(false);
    setSelectedType(relationship.attributes.relationship_type);
  };

  const handleSave = () => {
    // Validate the selected type
    const validationError = validateRequiredRelationshipType(selectedType);
    if (validationError) {
      return; // Don't save if validation fails
    }

    const updateData: ContactRelationshipFormData = {
      from_contact_id: relationship.attributes.from_contact_id,
      to_contact_id: relationship.attributes.to_contact_id ?? undefined,
      to_user: relationship.attributes.to_user,
      relationship_type: selectedType,
    };

    onUpdate(updateData);
    setIsEditing(false);
  };

  const handleDelete = () => {
    onDelete();
  };

  if (isEditing) {
    return (
      <div className='bg-muted/50 flex items-center gap-2 rounded-lg border p-3'>
        <User className='text-muted-foreground h-4 w-4' />
        <div className='flex-1'>
          {typesLoading ? (
            <div className='text-muted-foreground text-sm'>Loading...</div>
          ) : (
            <Select
              value={selectedType}
              onValueChange={value =>
                setSelectedType(value as RelationshipType)
              }
            >
              <SelectTrigger className='w-full'>
                <SelectValue placeholder='Select relationship type' />
              </SelectTrigger>
              <SelectContent>
                {relationshipTypes?.relationship_types?.map(type => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
        <div className='flex items-center gap-1'>
          <Button
            variant='ghost'
            size='sm'
            onClick={handleSave}
            disabled={disabled || typesLoading}
            aria-label='Save changes'
          >
            <Check className='h-4 w-4' />
            Save
          </Button>
          <Button
            variant='ghost'
            size='sm'
            onClick={handleCancel}
            disabled={disabled}
            aria-label='Cancel editing'
          >
            <X className='h-4 w-4' />
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className='hover:bg-muted/50 flex items-center gap-2 rounded-lg border p-3'>
      <User className='text-muted-foreground h-4 w-4' />
      <div className='flex-1'>
        <span className='font-medium'>
          {getTypeDisplayName(relationship.attributes.relationship_type)}
        </span>
        {contactName && (
          <>
            <span className='text-muted-foreground mx-1'>—</span>
            {isUserTargeted ? (
              <span
                className='text-primary font-medium'
                data-testid='relationship-user-target'
              >
                {contactName}
              </span>
            ) : otherContactId ? (
              <Link
                href={`/contacts/${otherContactId}`}
                className='text-primary hover:underline'
                data-testid={`relationship-contact-link-${otherContactId}`}
              >
                {contactName}
              </Link>
            ) : (
              <span className='font-medium'>{contactName}</span>
            )}
          </>
        )}
      </div>
      <div className='flex items-center gap-1'>
        <Button
          variant='ghost'
          size='sm'
          onClick={handleEdit}
          disabled={disabled}
          aria-label='Edit relationship'
        >
          <Edit2 className='h-4 w-4' />
        </Button>
        <Button
          variant='ghost'
          size='sm'
          onClick={handleDelete}
          disabled={disabled}
          aria-label='Delete relationship'
        >
          <Trash2 className='h-4 w-4' />
        </Button>
      </div>
    </div>
  );
}
