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

import { useState, useCallback, useRef } from 'react';
import { toast } from 'sonner';

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
  const originalValueRef = useRef(normalizedInitialValue);

  const startEdit = useCallback(() => {
    setIsEditing(true);
    setError(null);
    originalValueRef.current = displayValue;
  }, [displayValue]);

  const cancelEdit = useCallback(() => {
    setValue(originalValueRef.current);
    setDisplayValue(originalValueRef.current);
    setIsEditing(false);
    setError(null);
  }, []);

  const handleSetValue = useCallback(
    (newValue: string) => {
      setValue(newValue);

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
    if (error) {
      return;
    }

    // Don't save if value hasn't changed
    if (value === originalValueRef.current) {
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
      originalValueRef.current = value;

      if (showSuccessToast) {
        toast.success('Field updated successfully');
      }
    } catch (saveError) {
      // Rollback optimistic update
      setDisplayValue(originalValueRef.current);
      setValue(originalValueRef.current);
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
  }, [value, error, validation, onSave, showSuccessToast, showErrorToast]);

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

  return {
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
  };
}
