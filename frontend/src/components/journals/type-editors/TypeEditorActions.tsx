/**
 * Shared component for type editor action buttons.
 *
 * Provides consistent Edit/Save/Cancel button layout for all type editors.
 */

'use client';

import { Button } from '@/components/ui/button';

interface TypeEditorActionsProps {
  readonly isEditing: boolean;
  readonly onEdit: () => void;
  readonly onSave: () => void;
  readonly onCancel: () => void;
  readonly 'data-testid'?: string;
}

/**
 * TypeEditorActions component for consistent action buttons.
 *
 * @example
 * ```tsx
 * <TypeEditorActions
 *   isEditing={isEditing}
 *   onEdit={handleEdit}
 *   onSave={handleSave}
 *   onCancel={handleCancel}
 * />
 * ```
 */
export function TypeEditorActions({
  isEditing,
  onEdit,
  onSave,
  onCancel,
  'data-testid': testId,
}: TypeEditorActionsProps) {
  return (
    <div className='flex gap-2' data-testid={testId}>
      {isEditing ? (
        <>
          <Button
            variant='default'
            size='sm'
            onClick={onSave}
            data-testid='save-button'
          >
            Save
          </Button>
          <Button
            variant='outline'
            size='sm'
            onClick={onCancel}
            data-testid='cancel-button'
          >
            Cancel
          </Button>
        </>
      ) : (
        <Button
          variant='outline'
          size='sm'
          onClick={onEdit}
          data-testid='edit-button'
        >
          Edit
        </Button>
      )}
    </div>
  );
}
