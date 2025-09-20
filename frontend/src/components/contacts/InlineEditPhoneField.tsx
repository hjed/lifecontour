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
import {
  isValidPhoneNumber,
  parsePhoneNumberFromString,
  type CountryCode,
} from 'libphonenumber-js';
import { InlineEditField, type InlineEditFieldProps } from './InlineEditField';

export interface InlineEditPhoneFieldProps
  extends Omit<InlineEditFieldProps, 'fieldType' | 'validation'> {
  /** Whether to show phone icon in view mode */
  readonly showIcon?: boolean;
  /** Custom validation function (will be combined with phone validation) */
  readonly additionalValidation?: (value: string) => string | null;
  /** Default country code for phone number parsing and formatting (defaults to 'AU') */
  readonly defaultCountry?: CountryCode;
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
  defaultCountry = 'AU',
  className,
  'data-testid': testId,
  'aria-label': ariaLabel,
  ...props
}: InlineEditPhoneFieldProps) {
  // Country-aware phone validation
  const validatePhoneWithCountry = useCallback(
    (phoneValue: string) => {
      if (!phoneValue || phoneValue.trim().length === 0) return null;

      // First try to validate as international number (if it starts with +)
      if (phoneValue.trim().startsWith('+')) {
        const isValid = isValidPhoneNumber(phoneValue);
        return isValid ? null : 'Please enter a valid phone number';
      }

      // For national numbers, use the provided default country
      const isValid = isValidPhoneNumber(phoneValue, defaultCountry);
      return isValid ? null : 'Please enter a valid phone number';
    },
    [defaultCountry]
  );

  // Combine phone validation with any additional validation
  const validation = useCallback(
    (phoneValue: string) => {
      // First run phone validation
      const phoneError = validatePhoneWithCountry(phoneValue);
      if (phoneError) {
        return phoneError;
      }

      // Then run any additional validation
      if (additionalValidation) {
        return additionalValidation(phoneValue);
      }

      return null;
    },
    [validatePhoneWithCountry, additionalValidation]
  );

  // Country-aware phone formatting for display
  const formatForDisplay = useCallback(
    (phoneValue: string | null | undefined) => {
      if (!phoneValue) return phoneValue;

      try {
        // If the input starts with +, treat as international
        if (phoneValue.trim().startsWith('+')) {
          const phoneNumber = parsePhoneNumberFromString(phoneValue);
          if (phoneNumber && phoneNumber.isValid()) {
            return phoneNumber.formatInternational();
          }
        } else {
          // For national numbers, use the provided default country
          const phoneNumber = parsePhoneNumberFromString(
            phoneValue,
            defaultCountry
          );
          if (phoneNumber && phoneNumber.isValid()) {
            return phoneNumber.formatNational();
          }
        }
      } catch {
        // If parsing fails, fall back to original value
      }

      // If no valid phone number could be parsed, return original value
      return phoneValue;
    },
    [defaultCountry]
  );

  // Handle save with phone formatting
  const handleSave = useCallback(
    (phoneValue: string) => {
      // Format phone before saving
      const formattedPhone = formatForDisplay(phoneValue) || phoneValue;
      return onSave(formattedPhone);
    },
    [onSave, formatForDisplay]
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
