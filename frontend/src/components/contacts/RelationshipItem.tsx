/**
 * RelationshipItem component for displaying and editing individual relationships.
 *
 * Provides inline editing functionality for relationship types with
 * proper validation and error handling.
 */

'use client';

import { useState } from 'react';
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
  relationship: ContactRelationshipResource;
  onUpdate: (data: ContactRelationshipFormData) => void;
  onDelete: () => void;
  disabled?: boolean;
}

export function RelationshipItem({
  relationship,
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
    const typeData = relationshipTypes?.relationship_types?.find((t) => t.value === type);
    return typeData?.display_name || type;
  };

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
      to_contact_id: relationship.attributes.to_contact_id,
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
      <div className="flex items-center gap-2 p-3 border rounded-lg bg-muted/50">
        <User className="h-4 w-4 text-muted-foreground" />
        <div className="flex-1">
          {typesLoading ? (
            <div className="text-sm text-muted-foreground">Loading...</div>
          ) : (
            <Select
              value={selectedType}
              onValueChange={(value) => setSelectedType(value as RelationshipType)}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select relationship type" />
              </SelectTrigger>
              <SelectContent>
                {relationshipTypes?.relationship_types?.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    {type.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleSave}
            disabled={disabled || typesLoading}
            aria-label="Save changes"
          >
            <Check className="h-4 w-4" />
            Save
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCancel}
            disabled={disabled}
            aria-label="Cancel editing"
          >
            <X className="h-4 w-4" />
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 p-3 border rounded-lg hover:bg-muted/50">
      <User className="h-4 w-4 text-muted-foreground" />
      <div className="flex-1">
        <span className="font-medium">
          {getTypeDisplayName(relationship.attributes.relationship_type)}
        </span>
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={handleEdit}
          disabled={disabled}
          aria-label="Edit relationship"
        >
          <Edit2 className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleDelete}
          disabled={disabled}
          aria-label="Delete relationship"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
