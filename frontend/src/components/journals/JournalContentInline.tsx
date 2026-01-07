/**
 * Inline edit component for journal markdown content.
 *
 * Provides click-to-edit functionality for markdown content with a simple textarea.
 * Future enhancement: Add markdown preview toggle and toolbar.
 */

'use client';

import { useEffect, useRef } from 'react';
import { Check, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useInlineEdit } from '@/hooks/useInlineEdit';

export interface JournalContentInlineProps {
  /** Current content value (markdown) */
  readonly value: string;
  /** Callback when content is saved */
  readonly onSave: (value: string) => Promise<void>;
  /** Placeholder text when empty */
  readonly placeholder?: string;
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
 * Inline edit component for journal markdown content.
 * Displays rendered markdown in view mode, textarea in edit mode.
 */
export function JournalContentInline({
  value,
  onSave,
  placeholder = 'Click to add content',
  disabled = false,
  className,
  'data-testid': testId,
  'aria-label': ariaLabel,
}: JournalContentInlineProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
  } = useInlineEdit(value, onSave, undefined, {
    showErrorToast: false, // Show errors inline
  });

  // Focus textarea when entering edit mode
  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.focus();
      // Move cursor to end
      const length = textareaRef.current.value.length;
      textareaRef.current.setSelectionRange(length, length);
    }
  }, [isEditing]);

  const isEmpty = !displayValue || displayValue.trim() === '';

  // View mode - clickable display with markdown rendering
  if (!isEditing) {
    return (
      <div className={cn('group relative', className)} data-testid={testId}>
        <button
          type='button'
          className={cn(
            'w-full rounded-md px-3 py-2 text-left text-sm transition-colors',
            'hover:bg-muted focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
            disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent',
            isEmpty && 'text-muted-foreground italic'
          )}
          disabled={disabled}
          onClick={startEdit}
          aria-label={ariaLabel || `Click to edit content`}
        >
          {/* Simple text display for now - future: render markdown */}
          <div className='prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap'>
            {isEmpty ? placeholder : displayValue}
          </div>
        </button>
      </div>
    );
  }

  // Edit mode - textarea with save/cancel buttons
  return (
    <div className={cn('space-y-2', className)} data-testid={testId}>
      <Textarea
        ref={textareaRef}
        value={editValue}
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => {
          // Don't handle Enter for textarea (allow newlines)
          // Only handle Escape
          if (e.key === 'Escape') {
            e.preventDefault();
            cancelEdit();
          }
        }}
        placeholder={placeholder}
        disabled={isLoading}
        className={cn(
          'min-h-[200px] resize-y font-mono text-sm',
          error && 'border-destructive'
        )}
        aria-label={ariaLabel || 'Edit content'}
        aria-invalid={!!error}
        aria-describedby={error ? `${testId}-error` : undefined}
      />

      {/* Action buttons */}
      <div className='flex items-center gap-2'>
        <Button
          size='sm'
          onClick={saveEdit}
          disabled={isLoading}
          aria-label='Save content'
          data-testid={`${testId}-save`}
        >
          <Check className='mr-2 h-4 w-4' />
          Save
        </Button>
        <Button
          size='sm'
          variant='outline'
          onClick={cancelEdit}
          disabled={isLoading}
          aria-label='Cancel editing'
          data-testid={`${testId}-cancel`}
        >
          <X className='mr-2 h-4 w-4' />
          Cancel
        </Button>
        {isLoading && (
          <span className='text-muted-foreground text-sm'>Saving...</span>
        )}
      </div>

      {/* Error message */}
      {error && (
        <p
          id={`${testId}-error`}
          className='text-destructive text-sm'
          role='alert'
        >
          {error}
        </p>
      )}
    </div>
  );
}
