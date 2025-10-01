/**
 * AddRelationshipForm component for creating new contact relationships.
 *
 * Provides a form interface for selecting a contact and relationship type
 * with proper validation and error handling.
 */

'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ContactSearchCombobox } from './ContactSearchCombobox';
import { useRelationshipTypes } from '@/lib/api/relationships';
import {
  validateRequiredContactId,
  validateRequiredRelationshipType,
  parseContactId,
} from '@/lib/validation';
import {
  ContactResource,
  ContactRelationshipFormData,
  RelationshipType,
} from '@/types/contacts';

interface AddRelationshipFormProps {
  readonly contactId: string;
  readonly onSubmit: (data: ContactRelationshipFormData) => void;
  readonly onCancel: () => void;
  readonly disabled?: boolean;
}

export function AddRelationshipForm({
  contactId,
  onSubmit,
  onCancel,
  disabled = false,
}: AddRelationshipFormProps) {
  const [selectedContact, setSelectedContact] =
    useState<ContactResource | null>(null);
  const [selectedType, setSelectedType] = useState<RelationshipType | ''>('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  const { data: relationshipTypes, isLoading: typesLoading } =
    useRelationshipTypes();

  const handleContactSelect = (contact: ContactResource) => {
    setSelectedContact(contact);
    // Clear contact-related errors
    setErrors(prev => ({ ...prev, contact: '' }));
  };

  const handleTypeChange = (value: string) => {
    setSelectedType(value as RelationshipType);
    // Clear type-related errors
    setErrors(prev => ({ ...prev, relationship_type: '' }));
  };

  const handleSubmit = () => {
    // Validate form
    const newErrors: Record<string, string> = {};

    if (selectedContact) {
      const contactIdError = validateRequiredContactId(selectedContact.id);
      if (contactIdError) {
        newErrors.contact = contactIdError;
      }
    } else {
      newErrors.contact = 'Please select a contact';
    }

    const typeError = validateRequiredRelationshipType(selectedType);
    if (typeError) {
      newErrors.relationship_type = typeError;
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    // Validate and parse contact IDs using utility function
    const fromContactIdResult = parseContactId(contactId, 'from_contact_id');
    const toContactIdResult = parseContactId(
      selectedContact!.id,
      'to_contact_id'
    );

    if (fromContactIdResult.error) {
      setErrors(prev => ({
        ...prev,
        contact: fromContactIdResult.error!,
      }));
      return;
    }

    if (toContactIdResult.error) {
      setErrors(prev => ({
        ...prev,
        contact: toContactIdResult.error!,
      }));
      return;
    }

    // Submit form data
    const formData: ContactRelationshipFormData = {
      from_contact_id: fromContactIdResult.value!,
      to_contact_id: toContactIdResult.value!,
      relationship_type: selectedType as RelationshipType,
    };

    onSubmit(formData);

    // Reset form
    setSelectedContact(null);
    setSelectedType('');
    setErrors({});
  };

  const handleCancel = () => {
    // Reset form
    setSelectedContact(null);
    setSelectedType('');
    setErrors({});
    onCancel();
  };

  const isFormValid = selectedContact && selectedType && !disabled;

  return (
    <div className='bg-card space-y-4 rounded-lg border p-4'>
      <h3 className='text-lg font-semibold'>Add New Relationship</h3>

      <div className='space-y-4'>
        {/* Contact Selection */}
        <div className='space-y-2'>
          <Label htmlFor='contact-search'>Contact</Label>
          <ContactSearchCombobox
            onSelect={handleContactSelect}
            placeholder='Search for a contact...'
            excludeContactId={contactId}
            disabled={disabled}
          />
          {errors.contact && (
            <p className='text-destructive text-sm'>{errors.contact}</p>
          )}
          {selectedContact && (
            <p className='text-muted-foreground text-sm'>
              Selected: {selectedContact.attributes.first_name}{' '}
              {selectedContact.attributes.last_name}
            </p>
          )}
        </div>

        {/* Relationship Type Selection */}
        <div className='space-y-2'>
          <Label htmlFor='relationship-type'>Relationship Type</Label>
          {typesLoading ? (
            <div className='text-muted-foreground text-sm'>
              Loading relationship types...
            </div>
          ) : (
            <Select
              value={selectedType}
              onValueChange={handleTypeChange}
              disabled={disabled}
            >
              <SelectTrigger>
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
          {errors.relationship_type && (
            <p className='text-destructive text-sm'>
              {errors.relationship_type}
            </p>
          )}
        </div>
      </div>

      {/* Form Actions */}
      <div className='flex items-center gap-2 pt-4'>
        <Button
          onClick={handleSubmit}
          disabled={!isFormValid}
          className='flex-1'
        >
          Add Relationship
        </Button>
        <Button
          variant='outline'
          onClick={handleCancel}
          disabled={disabled}
          className='flex-1'
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}
