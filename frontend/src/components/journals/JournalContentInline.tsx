/**
 * Inline edit component for journal markdown content.
 *
 * Provides click-to-edit functionality for markdown content with a simple textarea.
 * Future enhancement: Add markdown preview toggle and toolbar.
 */

'use client';

import { Check, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { MarkdownEditor } from '@/components/journals/MarkdownEditor';
import { MarkdownRenderer } from '@/components/journals/MarkdownRenderer';
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

  const isEmpty = !displayValue || displayValue.trim() === '';

  // View mode - clickable display with markdown rendering
  if (!isEditing) {
    return (
      <div
        className={cn('group relative rounded-md', className)}
        data-testid={testId}
      >
        {/* Full-area edit affordance kept as a sibling (not a wrapper) so the
            rendered markdown — which contains block elements and links — is
            never nested inside a <button> (invalid HTML, breaks link clicks). */}
        <button
          type='button'
          className={cn(
            'absolute inset-0 z-0 w-full rounded-md transition-colors',
            'hover:bg-muted focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
            disabled && 'cursor-not-allowed hover:bg-transparent'
          )}
          disabled={disabled}
          onClick={startEdit}
          aria-label={ariaLabel || `Click to edit content`}
        />
        {/* Content sits above the button but is transparent to pointer events,
            so clicking anywhere enters edit mode — except links, which stay
            clickable so users can follow them without triggering an edit. */}
        <div
          className={cn(
            'pointer-events-none relative z-10 px-3 py-2 text-sm [&_a]:pointer-events-auto',
            disabled && 'opacity-50',
            isEmpty && 'text-muted-foreground italic'
          )}
        >
          {isEmpty ? (
            <span>{placeholder}</span>
          ) : (
            <MarkdownRenderer content={displayValue} />
          )}
        </div>
      </div>
    );
  }

  // Edit mode - markdown editor with save/cancel buttons
  return (
    <div className={cn('space-y-2', className)} data-testid={testId}>
      <MarkdownEditor
        value={editValue}
        onChange={setValue}
        onEscape={cancelEdit}
        focusOnMount
        placeholder={placeholder}
        disabled={isLoading}
        className={cn(error && 'border-destructive')}
        aria-label={ariaLabel || 'Edit content'}
        aria-invalid={!!error}
        aria-describedby={error ? `${testId}-error` : undefined}
        data-testid={testId ? `${testId}-editor` : undefined}
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
