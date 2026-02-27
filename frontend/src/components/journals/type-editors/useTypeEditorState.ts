/**
 * Shared hook for managing type editor state and actions.
 *
 * Provides common state management for inline editing workflow:
 * - Edit mode toggle
 * - Save/Cancel actions
 * - Data state management
 * - Create mode (always in edit mode, no save/cancel needed)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

interface UseTypeEditorStateOptions<T> {
  readonly initialData: T;
  readonly onSave?: (data: T) => Promise<void>;
  readonly onEdit?: (data: T) => T;
  /**
   * When true, the editor is always in edit mode (for use in create forms).
   * - isEditing is always true
   * - onEdit transformation is applied immediately to initialData
   * - handleSave and handleCancel are no-ops
   */
  readonly createMode?: boolean;
  /**
   * Called whenever the edit data changes (for parent form integration).
   * Useful in create mode to propagate changes to a parent form.
   * IMPORTANT: Parent components MUST memoize this callback (e.g., with useCallback)
   * to prevent infinite re-render loops in child effects.
   */
  readonly onChange?: (data: T) => void;
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
 * // Standard edit mode
 * const { isEditing, editData, setEditData, handleEdit, handleSave, handleCancel } =
 *   useTypeEditorState({
 *     initialData: data || defaultData,
 *     onSave,
 *   });
 *
 * // Create mode (always editing, no save/cancel)
 * const { editData, setEditData } =
 *   useTypeEditorState({
 *     initialData: defaultData,
 *     createMode: true,
 *     onChange: (data) => updateFormState(data),
 *   });
 * ```
 */
export function useTypeEditorState<T>({
  initialData,
  onSave,
  onEdit,
  createMode = false,
  onChange,
}: UseTypeEditorStateOptions<T>): UseTypeEditorStateReturn<T> {
  // In create mode, apply onEdit transformation to initialData immediately
  const computedInitialData = useMemo(() => {
    if (createMode && onEdit) {
      return onEdit(initialData);
    }
    return initialData;
  }, [createMode, onEdit, initialData]);

  const [isEditing, setIsEditing] = useState(createMode);
  const [editData, setEditDataState] = useState<T>(computedInitialData);

  // Wrap setEditData to call onChange when data changes
  const setEditData = useCallback(
    (data: T) => {
      setEditDataState(data);
      onChange?.(data);
    },
    [onChange]
  );

  // In create mode, immediately report initial data to parent on mount so that
  // the parent form captures the default state even without user interaction.
  const hasInitialised = useRef(false);
  useEffect(() => {
    if (createMode && !hasInitialised.current) {
      hasInitialised.current = true;
      onChange?.(computedInitialData);
    }
  }, [createMode, computedInitialData, onChange]);

  const handleEdit = useCallback(() => {
    if (createMode) {
      // No-op in create mode: always editing
      return;
    }
    // Allow transformation of data when entering edit mode
    if (onEdit) {
      setEditData(onEdit(editData));
    }
    setIsEditing(true);
  }, [createMode, editData, onEdit, setEditData]);

  const handleSave = useCallback(async () => {
    if (createMode) {
      // No-op in create mode: parent form handles save
      return;
    }
    if (onSave) {
      await onSave(editData);
      setIsEditing(false);
    }
  }, [createMode, editData, onSave]);

  const handleCancel = useCallback(() => {
    if (createMode) {
      // No-op in create mode: cannot cancel out of an inline create editor
      return;
    }
    setEditDataState(initialData);
    setIsEditing(false);
  }, [createMode, initialData]);

  return {
    isEditing,
    editData,
    setEditData,
    handleEdit,
    handleSave,
    handleCancel,
  };
}
