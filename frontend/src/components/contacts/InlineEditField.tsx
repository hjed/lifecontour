/**
 * Base inline edit field component.
 *
 * Provides click-to-edit functionality with optimistic updates,
 * validation, and accessibility support. Uses the useInlineEdit hook
 * for state management.
 */

'use client';

import { useEffect, useRef, useId } from 'react';
import { Check, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useInlineEdit } from '@/hooks/useInlineEdit';

export interface InlineEditFieldViewProps {
  /** Display text (value or placeholder) */
  readonly displayText: string;
  /** Whether the field is empty */
  readonly isEmpty: boolean;
  /** Handler for view mode click */
  readonly handleViewClick: () => void;
  /** Handler for view mode keyboard events */
  readonly handleViewKeyDown: (event: React.KeyboardEvent) => void;
}

export interface InlineEditFieldProps {
  /** Current field value */
  readonly value: string | null | undefined;
  /** Function to call when saving changes */
  readonly onSave: (value: string) => Promise<void>;
  /** Field type for input validation and formatting */
  readonly fieldType?: 'text' | 'email' | 'phone' | 'url';
  /** Placeholder text when value is empty */
  readonly placeholder?: string;
  /** Validation function that returns error message or null */
  readonly validation?: (value: string) => string | null;
  /** Whether the field is disabled */
  readonly disabled?: boolean;
  /** Additional CSS classes */
  readonly className?: string;
  /** Test ID for testing */
  readonly 'data-testid'?: string;
  /** ARIA label for accessibility */
  readonly 'aria-label'?: string;
  /** Custom render function for view mode (allows customization of the view element) */
  readonly renderView?: (props: InlineEditFieldViewProps) => React.ReactNode;
}

/**
 * Inline edit field component with click-to-edit functionality.
 */
export function InlineEditField({
  value,
  onSave,
  fieldType = 'text',
  placeholder = 'Click to edit',
  validation,
  disabled = false,
  className,
  'data-testid': testId,
  'aria-label': ariaLabel,
  renderView,
}: InlineEditFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const {
    value: editValue,
    displayValue,
    isEditing,
    isLoading,
    error,
    startEdit,
    cancelEdit,
    saveEdit,
    setValue,
    handleKeyDown,
  } = useInlineEdit(value, onSave, validation, {
    showErrorToast: false, // We'll show errors inline
  });

  // Focus input when entering edit mode
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  // Get input type based on field type
  const getInputType = () => {
    switch (fieldType) {
      case 'email':
        return 'email';
      case 'phone':
        return 'tel';
      case 'url':
        return 'url';
      default:
        return 'text';
    }
  };

  // Handle view mode click
  const handleViewClick = () => {
    if (!disabled) {
      startEdit();
    }
  };

  // Handle view mode keyboard events
  const handleViewKeyDown = (event: React.KeyboardEvent) => {
    if (!disabled && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      startEdit();
    }
  };

  // Generate unique IDs for accessibility
  const baseId = useId();
  const inputId = `inline-edit-${baseId}`;
  const errorId = `${inputId}-error`;

  if (isEditing) {
    return (
      <div
        className={cn('inline-flex flex-col gap-1', className)}
        data-testid={testId}
      >
        <div className='flex items-center gap-1'>
          <Input
            ref={inputRef}
            id={inputId}
            type={getInputType()}
            value={editValue}
            onChange={e => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            placeholder={placeholder}
            className={cn(
              'h-8 min-w-[120px]',
              error && 'border-destructive focus-visible:ring-destructive'
            )}
            aria-label={ariaLabel || 'Edit value'}
            aria-invalid={!!error}
            aria-describedby={error ? errorId : undefined}
            data-testid={testId ? `${testId}-input` : undefined}
          />

          <Button
            size='sm'
            variant='ghost'
            onClick={saveEdit}
            disabled={isLoading}
            className='h-8 w-8 p-0 text-green-600 hover:bg-green-50 hover:text-green-700'
            aria-label='Save changes'
          >
            <Check className='h-4 w-4' />
          </Button>

          <Button
            size='sm'
            variant='ghost'
            onClick={cancelEdit}
            disabled={isLoading}
            className='h-8 w-8 p-0 text-red-600 hover:bg-red-50 hover:text-red-700'
            aria-label='Cancel changes'
          >
            <X className='h-4 w-4' />
          </Button>
        </div>

        {error && (
          <div id={errorId} role='alert' className='text-destructive text-sm'>
            {error}
          </div>
        )}
      </div>
    );
  }

  // View mode
  const displayText = displayValue || placeholder;
  const isEmpty = !displayValue;

  // Use custom render function if provided
  if (renderView) {
    return (
      <>
        {renderView({
          displayText,
          isEmpty,
          handleViewClick,
          handleViewKeyDown,
        })}
      </>
    );
  }

  // Default view mode rendering
  return (
    <button
      type='button'
      className={cn(
        'inline-flex min-h-[32px] cursor-pointer items-center rounded-md px-2 py-1 text-sm transition-colors',
        'hover:bg-muted focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
        disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent',
        isEmpty && 'text-muted-foreground italic',
        className
      )}
      disabled={disabled}
      onClick={handleViewClick}
      onKeyDown={handleViewKeyDown}
      aria-label={ariaLabel || `Click to edit ${displayValue || 'empty field'}`}
      data-testid={testId}
    >
      {displayText}
    </button>
  );
}
