/**
 * Inline edit heading component.
 *
 * Provides click-to-edit functionality for headings with proper semantic HTML.
 * Renders as a heading element (h1-h6) in view mode for accessibility and SEO.
 */

'use client';

import { useEffect, useRef, useId } from 'react';
import { Check, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useInlineEdit } from '@/hooks/useInlineEdit';

export interface InlineEditHeadingProps {
  /** Current heading value */
  readonly value: string | null | undefined;
  /** Function to call when saving changes */
  readonly onSave: (value: string) => Promise<void>;
  /** Heading level (1-6) */
  readonly level?: 1 | 2 | 3 | 4 | 5 | 6;
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
}

/**
 * Inline edit heading component with click-to-edit functionality.
 * Renders as a semantic heading element in view mode.
 */
export function InlineEditHeading({
  value,
  onSave,
  level = 1,
  placeholder = 'Click to edit',
  validation,
  disabled = false,
  className,
  'data-testid': testId,
  'aria-label': ariaLabel,
}: InlineEditHeadingProps) {
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
  const inputId = `inline-edit-heading-${baseId}`;
  const errorId = `${inputId}-error`;

  // Edit mode
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
            type='text'
            value={editValue}
            onChange={e => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            placeholder={placeholder}
            className={cn(
              'h-10 min-w-[200px]',
              error && 'border-destructive focus-visible:ring-destructive'
            )}
            aria-label={ariaLabel || 'Edit heading'}
            aria-invalid={!!error}
            aria-describedby={error ? errorId : undefined}
            data-testid={testId ? `${testId}-input` : undefined}
          />

          <Button
            size='sm'
            variant='ghost'
            onClick={saveEdit}
            disabled={isLoading}
            className='h-10 w-10 p-0 text-green-600 hover:bg-green-50 hover:text-green-700'
            aria-label='Save changes'
          >
            <Check className='h-4 w-4' />
          </Button>

          <Button
            size='sm'
            variant='ghost'
            onClick={cancelEdit}
            disabled={isLoading}
            className='h-10 w-10 p-0 text-red-600 hover:bg-red-50 hover:text-red-700'
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

  // View mode - render as semantic heading
  const displayText = displayValue || placeholder;
  const isEmpty = !displayValue;

  // Create the heading element based on level
  const HeadingTag = `h${level}` as keyof JSX.IntrinsicElements;

  return (
    <HeadingTag
      className={cn(
        'cursor-pointer rounded-md px-2 py-1 transition-colors',
        'hover:bg-muted focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
        disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent',
        isEmpty && 'text-muted-foreground italic',
        className
      )}
      tabIndex={disabled ? -1 : 0}
      onClick={handleViewClick}
      onKeyDown={handleViewKeyDown}
      aria-label={
        ariaLabel || `Click to edit ${displayValue || 'empty heading'}`
      }
      data-testid={testId}
    >
      {displayText}
    </HeadingTag>
  );
}
