/**
 * RelationshipsList component for displaying and managing contact relationships.
 *
 * Provides a list view of relationships with add, edit, and delete functionality.
 * Integrates with the relationships API and provides proper loading and error states.
 */

'use client';

import { useState } from 'react';
import { Plus, Users, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { RelationshipItem } from './RelationshipItem';
import { AddRelationshipForm } from './AddRelationshipForm';
import {
  useContactRelationships,
  useCreateContactRelationship,
  useUpdateContactRelationship,
  useDeleteContactRelationship,
} from '@/lib/api/relationships';
import { ContactRelationshipFormData } from '@/types/contacts';

interface RelationshipsListProps {
  readonly contactId: string;
  readonly className?: string;
}

export function RelationshipsList({
  contactId,
  className,
}: RelationshipsListProps) {
  const [showAddForm, setShowAddForm] = useState(false);

  // API hooks
  const {
    data: relationshipsData,
    isLoading,
    error,
  } = useContactRelationships(contactId);

  const createMutation = useCreateContactRelationship();
  const updateMutation = useUpdateContactRelationship();
  const deleteMutation = useDeleteContactRelationship();

  const relationships = relationshipsData?.data || [];

  // Handle adding new relationship
  const handleAddRelationship = (data: ContactRelationshipFormData) => {
    createMutation.mutate(
      { contactId, data },
      {
        onSuccess: () => {
          setShowAddForm(false);
        },
      }
    );
  };

  // Handle updating relationship
  const handleUpdateRelationship = (
    relationshipId: string,
    data: ContactRelationshipFormData
  ) => {
    updateMutation.mutate({
      contactId,
      relationshipId,
      data,
    });
  };

  // Handle deleting relationship
  const handleDeleteRelationship = (relationshipId: string) => {
    deleteMutation.mutate({
      contactId,
      relationshipId,
    });
  };

  const isAnyMutationPending =
    createMutation.isPending ||
    updateMutation.isPending ||
    deleteMutation.isPending;

  return (
    <Card className={className}>
      <CardHeader>
        <div className='flex items-center justify-between'>
          <CardTitle className='flex items-center gap-2'>
            <Users className='h-5 w-5' />
            Relationships
          </CardTitle>
          {!showAddForm && (
            <Button
              variant='outline'
              size='sm'
              onClick={() => setShowAddForm(true)}
              disabled={isAnyMutationPending}
            >
              <Plus className='mr-1 h-4 w-4' />
              Add Relationship
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className='flex items-center gap-2 py-4'>
            <Loader2 className='h-4 w-4 animate-spin' />
            <span>Loading relationships...</span>
          </div>
        )}

        {error && (
          <div className='text-destructive py-4'>
            <span>Error loading relationships</span>
          </div>
        )}

        {!isLoading && !error && relationships.length === 0 && !showAddForm && (
          <div className='text-muted-foreground py-8 text-center'>
            <Users className='mx-auto mb-4 h-12 w-12 opacity-50' />
            <p className='mb-2 text-lg font-medium'>No relationships yet</p>
            <p className='text-sm'>
              Add relationships to connect this contact with others
            </p>
          </div>
        )}

        {!isLoading && !error && relationships.length > 0 && (
          <div className='space-y-3'>
            {relationships.map(relationship => (
              <RelationshipItem
                key={relationship.id}
                relationship={relationship}
                onUpdate={data =>
                  handleUpdateRelationship(relationship.id, data)
                }
                onDelete={() => handleDeleteRelationship(relationship.id)}
                disabled={isAnyMutationPending}
              />
            ))}
          </div>
        )}

        {showAddForm && (
          <div className='mt-4'>
            <AddRelationshipForm
              contactId={contactId}
              onSubmit={handleAddRelationship}
              onCancel={() => setShowAddForm(false)}
              disabled={createMutation.isPending}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
