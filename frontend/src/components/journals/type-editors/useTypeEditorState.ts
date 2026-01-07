/**
 * Shared hook for managing type editor state and actions.
 *
 * Provides common state management for inline editing workflow:
 * - Edit mode toggle
 * - Save/Cancel actions
 * - Data state management
 */

import { useCallback, useState } from 'react';

interface UseTypeEditorStateOptions<T> {
  readonly initialData: T;
  readonly onSave?: (data: T) => Promise<void>;
  readonly onEdit?: (data: T) => T;
}

interface UseTypeEditorStateReturn<T> {
  readonly isEditing: boolean;
  readonly editData: T;
  readonly setEditData: (data: T) => void;
  readonly handleEdit: () => void;
  readonly handleSave: () => Promise<void>;
  readonly handleCancel: () => void;
}

/**
 * Hook for managing type editor state.
 *
 * @example
 * ```tsx
 * const { isEditing, editData, setEditData, handleEdit, handleSave, handleCancel } =
 *   useTypeEditorState({
 *     initialData: data || defaultData,
 *     onSave,
 *   });
 * ```
 */
export function useTypeEditorState<T>({
  initialData,
  onSave,
  onEdit,
}: UseTypeEditorStateOptions<T>): UseTypeEditorStateReturn<T> {
  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState<T>(initialData);

  const handleEdit = useCallback(() => {
    // Allow transformation of data when entering edit mode
    if (onEdit) {
      setEditData(onEdit(editData));
    }
    setIsEditing(true);
  }, [editData, onEdit]);

  const handleSave = useCallback(async () => {
    if (onSave) {
      await onSave(editData);
      setIsEditing(false);
    }
  }, [editData, onSave]);

  const handleCancel = useCallback(() => {
    setEditData(initialData);
    setIsEditing(false);
  }, [initialData]);

  return {
    isEditing,
    editData,
    setEditData,
    handleEdit,
    handleSave,
    handleCancel,
  };
}
