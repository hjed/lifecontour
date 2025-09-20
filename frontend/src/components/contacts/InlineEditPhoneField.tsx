/**
 * Specialized inline edit field for phone numbers.
 *
 * Provides phone number formatting during editing and display,
 * with international phone number validation and proper formatting.
 */

'use client';

import { useCallback } from 'react';
import { Phone } from 'lucide-react';
import { cn } from '@/lib/utils';
import { validatePhone, formatPhoneNumber } from '@/lib/validation';
import { InlineEditField, type InlineEditFieldProps } from './InlineEditField';

export interface InlineEditPhoneFieldProps
  extends Omit<InlineEditFieldProps, 'fieldType' | 'validation'> {
  /** Whether to show phone icon in view mode */
  readonly showIcon?: boolean;
  /** Custom validation function (will be combined with phone validation) */
  readonly additionalValidation?: (value: string) => string | null;
}

/**
 * Inline edit field specialized for phone numbers with formatting and validation.
 */
export function InlineEditPhoneField({
  value,
  onSave,
  placeholder = 'Add phone number',
  showIcon = true,
  additionalValidation,
  className,
  'data-testid': testId,
  'aria-label': ariaLabel,
  ...props
}: InlineEditPhoneFieldProps) {
  // Combine phone validation with any additional validation
  const validation = useCallback(
    (phoneValue: string) => {
      // First run phone validation
      const phoneError = validatePhone(phoneValue);
      if (phoneError) {
        return phoneError;
      }

      // Then run any additional validation
      if (additionalValidation) {
        return additionalValidation(phoneValue);
      }

      return null;
    },
    [additionalValidation]
  );

  // Format phone number for display
  const formatForDisplay = useCallback(
    (phoneValue: string | null | undefined) => {
      if (!phoneValue) return phoneValue;
      return formatPhoneNumber(phoneValue);
    },
    []
  );

  // Format phone number during editing (incomplete formatting)

  // Handle save with formatting
  const handleSave = useCallback(
    async (phoneValue: string) => {
      // Format the phone number before saving
      const formattedPhone = formatPhoneNumber(phoneValue);
      await onSave(formattedPhone);
    },
    [onSave]
  );

  // Format the display value
  const displayValue = formatForDisplay(value);

  return (
    <div className='inline-flex items-center gap-2'>
      {showIcon && (
        <Phone
          className='text-muted-foreground h-4 w-4 flex-shrink-0'
          aria-hidden='true'
        />
      )}
      <InlineEditField
        {...props}
        value={displayValue}
        onSave={handleSave}
        fieldType='phone'
        placeholder={placeholder}
        validation={validation}
        className={cn('min-w-[160px]', className)}
        data-testid={testId}
        aria-label={ariaLabel || 'Phone number'}
      />
    </div>
  );
}
