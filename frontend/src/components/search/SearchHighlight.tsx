/**
 * SearchHighlight component for rendering text with search term highlighting.
 *
 * Safely renders HTML content with <mark> tags from MeiliSearch highlighting,
 * providing visual emphasis for search matches while preventing XSS attacks.
 */

import React from 'react';
import DOMPurify from 'dompurify';
import { cn } from '@/lib/utils';

interface SearchHighlightProps {
  /** The text content to display, may contain <mark> tags for highlighting */
  text: string;
  /** Optional fallback text to display if highlighted text is empty */
  fallback?: string;
  /** Additional CSS classes to apply to the container */
  className?: string;
  /** Whether to show the fallback when text is empty (default: true) */
  showFallback?: boolean;
}

/**
 * Safely renders text with search highlighting from MeiliSearch.
 *
 * This component takes text that may contain <mark> tags from MeiliSearch
 * highlighting and renders it safely. It only allows <mark> tags and strips
 * any other HTML to prevent XSS attacks.
 *
 * @param text - Text with potential <mark> tags for highlighting
 * @param fallback - Text to show if highlighted text is empty
 * @param className - Additional CSS classes
 * @param showFallback - Whether to show fallback text when main text is empty
 */
export function SearchHighlight({
  text,
  fallback = '',
  className,
  showFallback = true,
}: SearchHighlightProps) {
  // If no text and no fallback, return null
  if (!text && (!fallback || !showFallback)) {
    return null;
  }

  // Use fallback if text is empty
  const displayText = text || fallback;

  // If no highlighting tags present, return plain text
  if (!displayText.includes('<mark>')) {
    return (
      <span className={cn('search-highlight', className)}>{displayText}</span>
    );
  }

  // Safely parse and render highlighted content using DOMPurify
  // Only allow <mark> tags, strip everything else for security
  const sanitizedHtml = DOMPurify.sanitize(displayText, {
    ALLOWED_TAGS: ['mark'],
    ALLOWED_ATTR: [], // No attributes allowed for security
  });

  // Add styling to mark tags after sanitization
  const styledHtml = sanitizedHtml.replace(
    /<mark>/g,
    '<mark class="bg-yellow-200 dark:bg-yellow-800 px-1 rounded">'
  );

  return (
    <span
      className={cn('search-highlight', className)}
      dangerouslySetInnerHTML={{ __html: styledHtml }}
    />
  );
}

/**
 * Hook to extract highlighted text from search metadata.
 *
 * @param highlighted - The highlighted object from search results
 * @param field - The field name to extract highlighting for
 * @param fallback - Fallback text if no highlighting available
 * @returns The highlighted text or fallback
 */
export function useHighlightedText(
  highlighted: Record<string, unknown> | null | undefined,
  field: string,
  fallback: string = ''
): string {
  if (!highlighted || typeof highlighted !== 'object') {
    return fallback;
  }

  const highlightedValue = highlighted[field];

  if (typeof highlightedValue === 'string') {
    return highlightedValue;
  }

  return fallback;
}

/**
 * Component for displaying a field with potential highlighting.
 *
 * This is a convenience component that combines SearchHighlight with
 * the useHighlightedText hook for common use cases.
 */
interface HighlightedFieldProps {
  /** The highlighted object from search results */
  highlighted: Record<string, unknown> | null | undefined;
  /** The field name to extract highlighting for */
  field: string;
  /** Fallback text if no highlighting available */
  fallback: string;
  /** Additional CSS classes */
  className?: string;
  /** Optional label to display before the field */
  label?: string;
  /** Whether to show the field if fallback is empty */
  showEmpty?: boolean;
}

export function HighlightedField({
  highlighted,
  field,
  fallback,
  className,
  label,
  showEmpty = false,
}: HighlightedFieldProps) {
  const highlightedText = useHighlightedText(highlighted, field, fallback);

  // Don't render if no text and showEmpty is false
  if (!highlightedText && !showEmpty) {
    return null;
  }

  return (
    <div className={cn('highlighted-field', className)}>
      {label && <span className='mr-1 font-medium'>{label}:</span>}
      <SearchHighlight
        text={highlightedText}
        fallback={fallback}
        showFallback={showEmpty}
      />
    </div>
  );
}
