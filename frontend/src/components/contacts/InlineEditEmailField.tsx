/**
 * Specialized inline edit field for email addresses.
 *
 * Provides email validation and enhanced UX with email icon
 * and proper email input type for better mobile keyboards.
 */

'use client';

import { useCallback } from 'react';
import { Mail } from 'lucide-react';
import { cn } from '@/lib/utils';
import { validateEmail } from '@/lib/validation';
import { InlineEditField, type InlineEditFieldProps } from './InlineEditField';

export interface InlineEditEmailFieldProps extends Omit<
  InlineEditFieldProps,
  'fieldType' | 'validation'
> {
  /** Whether to show email icon in view mode */
  readonly showIcon?: boolean;
  /** Custom validation function (will be combined with email validation) */
  readonly additionalValidation?: (value: string) => string | null;
}

/**
 * Inline edit field specialized for email addresses with validation.
 */
export function InlineEditEmailField({
  value,
  onSave,
  placeholder = 'Add email address',
  showIcon = true,
  additionalValidation,
  className,
  'data-testid': testId,
  'aria-label': ariaLabel,
  ...props
}: InlineEditEmailFieldProps) {
  // Combine email validation with any additional validation
  const validation = useCallback(
    (emailValue: string) => {
      // Normalize email: trim whitespace and convert to lowercase
      const normalizedEmail = emailValue.trim().toLowerCase();

      // First run email validation
      const emailError = validateEmail(normalizedEmail);
      if (emailError) {
        return emailError;
      }

      // Then run any additional validation
      if (additionalValidation) {
        return additionalValidation(normalizedEmail);
      }

      return null;
    },
    [additionalValidation]
  );

  // Handle save with email normalization
  const handleSave = useCallback(
    (emailValue: string) => {
      // Normalize email before saving
      const normalizedEmail = emailValue.trim().toLowerCase();
      return onSave(normalizedEmail);
    },
    [onSave]
  );

  return (
    <div className='inline-flex items-center gap-2'>
      {showIcon && (
        <Mail
          className='text-muted-foreground h-4 w-4 flex-shrink-0'
          aria-hidden='true'
        />
      )}
      <InlineEditField
        {...props}
        value={value}
        onSave={handleSave}
        fieldType='email'
        placeholder={placeholder}
        validation={validation}
        className={cn('min-w-[200px]', className)}
        data-testid={testId}
        aria-label={ariaLabel || 'Email address'}
      />
    </div>
  );
}
