/**
 * Hook for inline editing functionality with optimistic updates.
 *
 * Provides state management for inline editing with support for:
 * - Edit/view mode transitions
 * - Optimistic updates with rollback on errors
 * - Field validation
 * - Keyboard shortcuts (Enter to save, Escape to cancel)
 * - Loading states and error handling
 */

import { useState, useCallback, useMemo } from 'react';
import { toast } from 'sonner';
import { isWriteConflict } from '@/lib/write-conflicts';

export interface UseInlineEditOptions {
  /** Validation function that returns error message or null */
  validation?: (value: string) => string | null;
  /** Whether to show success toast on save */
  showSuccessToast?: boolean;
  /** Whether to show error toast on save failure */
  showErrorToast?: boolean;
}

export interface UseInlineEditReturn {
  /** Current value being edited */
  value: string;
  /** Value displayed to user (for optimistic updates) */
  displayValue: string;
  /** Whether currently in edit mode */
  isEditing: boolean;
  /** Whether save operation is in progress */
  isLoading: boolean;
  /** Current validation or save error */
  error: string | null;
  /** Start editing mode */
  startEdit: () => void;
  /** Cancel editing and revert to original value */
  cancelEdit: () => void;
  /** Save current value */
  saveEdit: () => Promise<void>;
  /** Update current value */
  setValue: (newValue: string) => void;
  /** Handle keyboard shortcuts */
  handleKeyDown: (event: React.KeyboardEvent) => Promise<void>;
}

/**
 * Hook for managing inline edit state with optimistic updates.
 *
 * @param initialValue - Initial value for the field
 * @param onSave - Function to call when saving (should return a promise)
 * @param validation - Optional validation function
 * @param options - Additional options
 */
export function useInlineEdit(
  initialValue: string | null | undefined,
  onSave: (value: string) => Promise<void>,
  validation?: (value: string) => string | null,
  options: UseInlineEditOptions = {}
): UseInlineEditReturn {
  const { showSuccessToast = false, showErrorToast = true } = options;

  // Normalize initial value to string
  const normalizedInitialValue = initialValue ?? '';

  // State management
  const [value, setValue] = useState(normalizedInitialValue);
  const [displayValue, setDisplayValue] = useState(normalizedInitialValue);
  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Keep track of original value for rollback
  const [originalValue, setOriginalValue] = useState(normalizedInitialValue);
  const [prevInitialValue, setPrevInitialValue] = useState(initialValue);
  // Set when a save was refused as a write conflict: the record has been
  // re-read, so the field shows whatever the cache now holds.
  const [resyncPending, setResyncPending] = useState(false);
  // The value the field took on elsewhere while it was being edited, until
  // the user has seen it. A refetch that brings it also brings the record's
  // newer tag, so saving the draft as-is would overwrite it unrefused.
  const [changedWhileEditing, setChangedWhileEditing] = useState<string | null>(
    null
  );
  // Whether the error showing is that notice rather than a validation error,
  // so the second save it asks for is not blocked by it.
  const [staleWarned, setStaleWarned] = useState(false);

  if (resyncPending) {
    setResyncPending(false);
    setDisplayValue(normalizedInitialValue);
    setValue(normalizedInitialValue);
    setOriginalValue(normalizedInitialValue);
  }

  // Sync external changes (e.g. from react-query refetches) when not actively editing
  if (initialValue !== prevInitialValue) {
    setPrevInitialValue(initialValue);
    if (isEditing && initialValue !== undefined) {
      setChangedWhileEditing(initialValue ?? '');
    }
    if (!isEditing && initialValue !== undefined) {
      const normalized = initialValue ?? '';

      setDisplayValue(normalized);

      setValue(normalized);
      setOriginalValue(normalized);
    }
  }

  const startEdit = useCallback(() => {
    // Not while a save is in flight: its outcome — a conflict re-read, say —
    // resyncs the field, which an open editor would hold back.
    if (isLoading) return;
    setIsEditing(true);
    setError(null);
    setOriginalValue(displayValue);
  }, [displayValue, isLoading]);

  const cancelEdit = useCallback(() => {
    const restored = changedWhileEditing ?? originalValue;
    setChangedWhileEditing(null);
    setValue(restored);
    setDisplayValue(restored);
    setOriginalValue(restored);
    setIsEditing(false);
    setError(null);
  }, [changedWhileEditing, originalValue]);

  const handleSetValue = useCallback(
    (newValue: string) => {
      setValue(newValue);
      // Editing on replaces the notice; validation below decides the error.
      setStaleWarned(false);

      // Run validation if provided
      if (validation) {
        const validationError = validation(newValue);
        setError(validationError);
      } else {
        setError(null);
      }
    },
    [validation]
  );

  const saveEdit = useCallback(async () => {
    // Don't save if there's a validation error
    if (error && !staleWarned) {
      return;
    }
    setStaleWarned(false);

    // The field changed elsewhere since editing began: say so once, and let
    // a second save replace it knowingly.
    if (changedWhileEditing !== null) {
      setChangedWhileEditing(null);
      setOriginalValue(changedWhileEditing);
      if (value !== changedWhileEditing) {
        setError(
          `This was changed elsewhere to “${changedWhileEditing}” while you were editing. Save again to replace it.`
        );
        setStaleWarned(true);
        return;
      }
    }

    // Don't save if value hasn't changed
    if (value === originalValue) {
      setIsEditing(false);
      return;
    }

    // Run final validation
    if (validation) {
      const validationError = validation(value);
      if (validationError) {
        setError(validationError);
        return;
      }
    }

    setIsLoading(true);
    setError(null);

    // Optimistic update
    setDisplayValue(value);
    setIsEditing(false);

    try {
      await onSave(value);

      // Update original value reference for future edits
      setOriginalValue(value);

      if (showSuccessToast) {
        toast.success('Field updated successfully');
      }
    } catch (saveError) {
      if (isWriteConflict(saveError)) {
        // The conflict dialog reports it and offers to re-apply the value, so
        // the field closes rather than holding a second copy of the edit.
        setResyncPending(true);
        return;
      }

      // Rollback optimistic update
      setDisplayValue(originalValue);
      setValue(originalValue);
      setIsEditing(true);

      const errorMessage =
        saveError instanceof Error
          ? saveError.message
          : 'Failed to save changes';

      setError(errorMessage);

      if (showErrorToast) {
        toast.error(errorMessage);
      }
    } finally {
      setIsLoading(false);
    }
  }, [
    value,
    originalValue,
    error,
    staleWarned,
    changedWhileEditing,
    validation,
    onSave,
    showSuccessToast,
    showErrorToast,
  ]);

  const handleKeyDown = useCallback(
    async (event: React.KeyboardEvent) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        await saveEdit();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        cancelEdit();
      }
    },
    [saveEdit, cancelEdit]
  );

  return useMemo(
    () => ({
      value,
      displayValue,
      isEditing,
      isLoading,
      error,
      startEdit,
      cancelEdit,
      saveEdit,
      setValue: handleSetValue,
      handleKeyDown,
    }),
    [
      value,
      displayValue,
      isEditing,
      isLoading,
      error,
      startEdit,
      cancelEdit,
      saveEdit,
      handleSetValue,
      handleKeyDown,
    ]
  );
}
