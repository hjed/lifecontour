/**
 * Tests for useInlineEdit hook.
 *
 * Tests the core inline editing functionality including state management,
 * optimistic updates, error handling, and rollback capabilities.
 */

import { renderHook, act } from '@testing-library/react';
import { useInlineEdit } from '@/hooks/useInlineEdit';
import { PreconditionFailedError } from '@/lib/api/conditional-request';

// Mock toast notifications
jest.mock('sonner', () => ({
  toast: {
    error: jest.fn(),
    success: jest.fn(),
  },
}));

describe('useInlineEdit', () => {
  const mockOnSave = jest.fn();
  const mockValidation = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial state', () => {
    it('should initialize with view mode and initial value', () => {
      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      expect(result.current.isEditing).toBe(false);
      expect(result.current.value).toBe('initial value');
      expect(result.current.displayValue).toBe('initial value');
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('should handle empty initial value', () => {
      const { result } = renderHook(() => useInlineEdit('', mockOnSave));

      expect(result.current.value).toBe('');
      expect(result.current.displayValue).toBe('');
    });

    it('should handle null initial value', () => {
      const { result } = renderHook(() => useInlineEdit(null, mockOnSave));

      expect(result.current.value).toBe('');
      expect(result.current.displayValue).toBe('');
    });

    it('should handle undefined initial value', () => {
      const { result } = renderHook(() => useInlineEdit(undefined, mockOnSave));

      expect(result.current.value).toBe('');
      expect(result.current.displayValue).toBe('');
    });
  });

  describe('edit mode', () => {
    it('should enter edit mode when startEdit is called', () => {
      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      expect(result.current.isEditing).toBe(true);
      expect(result.current.value).toBe('initial value');
    });

    it('should update value during editing', () => {
      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('new value');
      });

      expect(result.current.value).toBe('new value');
      expect(result.current.isEditing).toBe(true);
    });

    it('should cancel edit and revert to original value', () => {
      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('changed value');
      });

      act(() => {
        result.current.cancelEdit();
      });

      expect(result.current.isEditing).toBe(false);
      expect(result.current.value).toBe('initial value');
      expect(result.current.displayValue).toBe('initial value');
    });
  });

  describe('validation', () => {
    it('should validate value when provided', () => {
      mockValidation.mockReturnValue('Validation error');

      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave, mockValidation)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('invalid value');
      });

      expect(mockValidation).toHaveBeenCalledWith('invalid value');
      expect(result.current.error).toBe('Validation error');
    });

    it('should clear error when validation passes', () => {
      mockValidation.mockReturnValueOnce('Validation error');
      mockValidation.mockReturnValueOnce(null);

      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave, mockValidation)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('invalid value');
      });

      expect(result.current.error).toBe('Validation error');

      act(() => {
        result.current.setValue('valid value');
      });

      expect(result.current.error).toBeNull();
    });

    it('should prevent save when validation fails', async () => {
      mockValidation.mockReturnValue('Validation error');

      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave, mockValidation)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('invalid value');
      });

      await act(async () => {
        await result.current.saveEdit();
      });

      expect(mockOnSave).not.toHaveBeenCalled();
      expect(result.current.isEditing).toBe(true);
    });
  });

  describe('save functionality', () => {
    it('should save successfully with optimistic update', async () => {
      mockOnSave.mockResolvedValue(undefined);

      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('new value');
      });

      await act(async () => {
        await result.current.saveEdit();
      });

      expect(mockOnSave).toHaveBeenCalledWith('new value');
      expect(result.current.isEditing).toBe(false);
      expect(result.current.displayValue).toBe('new value');
    });

    it('should handle save errors with rollback', async () => {
      const saveError = new Error('Save failed');
      mockOnSave.mockRejectedValue(saveError);

      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('new value');
      });

      await act(async () => {
        await result.current.saveEdit();
      });

      expect(result.current.isEditing).toBe(true);
      expect(result.current.displayValue).toBe('initial value'); // Rolled back
      expect(result.current.value).toBe('initial value'); // Rolled back in edit mode too
      expect(result.current.error).toBe('Save failed');
    });

    it('should show loading state during save', async () => {
      let resolvePromise: (value: unknown) => void;
      const savePromise = new Promise(resolve => {
        resolvePromise = resolve;
      });
      mockOnSave.mockReturnValue(savePromise);

      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('new value');
      });

      act(() => {
        result.current.saveEdit();
      });

      expect(result.current.isLoading).toBe(true);

      await act(async () => {
        resolvePromise(undefined);
        await savePromise;
      });

      expect(result.current.isLoading).toBe(false);
    });

    it('should not save if value unchanged', async () => {
      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      await act(async () => {
        await result.current.saveEdit();
      });

      expect(mockOnSave).not.toHaveBeenCalled();
      expect(result.current.isEditing).toBe(false);
    });
  });

  describe('keyboard shortcuts', () => {
    it('should save on Enter key', async () => {
      mockOnSave.mockResolvedValue(undefined);

      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('new value');
      });

      const mockEvent = {
        key: 'Enter',
        preventDefault: jest.fn(),
      } as unknown as React.KeyboardEvent;

      await act(async () => {
        await result.current.handleKeyDown(mockEvent);
      });

      expect(mockEvent.preventDefault).toHaveBeenCalled();
      expect(mockOnSave).toHaveBeenCalledWith('new value');
      expect(result.current.isEditing).toBe(false);
    });

    it('should cancel on Escape key', () => {
      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      act(() => {
        result.current.setValue('changed value');
      });

      const mockEvent = {
        key: 'Escape',
        preventDefault: jest.fn(),
      } as unknown as React.KeyboardEvent;

      act(() => {
        result.current.handleKeyDown(mockEvent);
      });

      expect(mockEvent.preventDefault).toHaveBeenCalled();
      expect(result.current.isEditing).toBe(false);
      expect(result.current.value).toBe('initial value');
    });

    it('should ignore other keys', () => {
      const { result } = renderHook(() =>
        useInlineEdit('initial value', mockOnSave)
      );

      act(() => {
        result.current.startEdit();
      });

      const mockEvent = {
        key: 'Tab',
        preventDefault: jest.fn(),
      } as unknown as React.KeyboardEvent;

      act(() => {
        result.current.handleKeyDown(mockEvent);
      });

      expect(mockEvent.preventDefault).not.toHaveBeenCalled();
      expect(result.current.isEditing).toBe(true);
    });
  });
  describe('write conflicts', () => {
    const conflict = () =>
      new PreconditionFailedError('moved on', 'PRECONDITION_FAILED', {});

    async function saveRefused(initial: string) {
      const onSave = jest.fn().mockRejectedValue(conflict());
      const hook = renderHook(
        ({ value }) => useInlineEdit(value, onSave, undefined, {}),
        { initialProps: { value: initial } }
      );
      act(() => hook.result.current.startEdit());
      act(() => hook.result.current.setValue('mine'));
      return { hook, save: () => hook.result.current.saveEdit() };
    }

    it('leaves edit mode without an error or toast, since the conflict dialog reports it', async () => {
      const { hook, save } = await saveRefused('original');

      await act(save);

      expect(hook.result.current.isEditing).toBe(false);
      expect(hook.result.current.error).toBeNull();
      expect(hook.result.current.displayValue).toBe('original');
      const { toast } = jest.requireMock('sonner');
      expect(toast.error).not.toHaveBeenCalled();
    });

    it('shows the value re-read with the conflict, not the one it replaced', async () => {
      const { hook, save } = await saveRefused('original');

      // The conflict handler re-reads the record before the save rejects.
      await act(async () => {
        const saving = save();
        hook.rerender({ value: 'theirs' });
        await saving;
      });

      expect(hook.result.current.displayValue).toBe('theirs');
    });
  });

  describe('the field changing while it is being edited', () => {
    function editing(
      initial: string,
      onSave = jest.fn().mockResolvedValue(undefined)
    ) {
      const hook = renderHook(
        ({ value }) => useInlineEdit(value, onSave, undefined, {}),
        { initialProps: { value: initial } }
      );
      act(() => hook.result.current.startEdit());
      act(() => hook.result.current.setValue('mine'));
      return { hook, onSave };
    }

    it('asks before replacing a value that changed elsewhere since editing began', async () => {
      // A refetch brought the other tab's value, and with it the newer tag:
      // sending the draft now would overwrite that value unrefused.
      const { hook, onSave } = editing('original');
      hook.rerender({ value: 'theirs' });

      await act(() => hook.result.current.saveEdit());

      expect(onSave).not.toHaveBeenCalled();
      expect(hook.result.current.isEditing).toBe(true);
      expect(hook.result.current.value).toBe('mine');
      expect(hook.result.current.error).toBe(
        'This was changed elsewhere to “theirs” while you were editing. Save again to replace it.'
      );

      await act(() => hook.result.current.saveEdit());

      expect(onSave).toHaveBeenCalledWith('mine');
    });

    it('cancels back to the value that changed elsewhere', () => {
      const { hook } = editing('original');
      hook.rerender({ value: 'theirs' });

      act(() => hook.result.current.cancelEdit());

      expect(hook.result.current.displayValue).toBe('theirs');
    });

    it('cannot be reopened while a save is in flight', async () => {
      let finish!: () => void;
      const onSave = jest.fn(
        () => new Promise<void>(resolve => (finish = resolve))
      );
      const { hook } = editing('original', onSave);
      let saving!: Promise<void>;
      act(() => {
        saving = hook.result.current.saveEdit();
      });

      act(() => hook.result.current.startEdit());

      expect(hook.result.current.isEditing).toBe(false);
      await act(async () => {
        finish();
        await saving;
      });
    });
  });
});
