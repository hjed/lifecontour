/**
 * Inline edit heading component.
 *
 * Provides click-to-edit functionality for headings with proper semantic HTML.
 * Renders as a heading element (h1-h6) in view mode for accessibility and SEO.
 * Uses InlineEditField internally but renders as a semantic heading in view mode.
 */

'use client';

import { cn } from '@/lib/utils';
import { InlineEditField } from '@/components/contacts/InlineEditField';

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
 *
 * This is a thin wrapper around InlineEditField that customizes the view mode
 * to render as a semantic heading element for better accessibility and SEO.
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
  // Create the heading element based on level
  const HeadingTag = `h${level}` as keyof JSX.IntrinsicElements;

  return (
    <InlineEditField
      value={value}
      onSave={onSave}
      placeholder={placeholder}
      validation={validation}
      disabled={disabled}
      className={className}
      data-testid={testId}
      aria-label={ariaLabel}
      // Customize rendering for heading
      renderView={({
        displayText,
        isEmpty,
        handleViewClick,
        handleViewKeyDown,
      }) => {
        // Only use aria-label if explicitly provided or if the heading is empty
        // Otherwise, the visible text content serves as the accessible name
        const ariaLabelValue =
          ariaLabel || (isEmpty ? 'Click to edit empty heading' : undefined);

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
            aria-label={ariaLabelValue}
            data-testid={testId}
          >
            {displayText}
          </HeadingTag>
        );
      }}
    />
  );
}
