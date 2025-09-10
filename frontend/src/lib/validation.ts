/**
 * Field validation utilities.
 *
 * Provides validation functions for different field types including
 * email, phone, URL validation and formatting utilities.
 * Uses libphonenumber-js for international phone number validation and formatting.
 */

import {
  parsePhoneNumberFromString,
  isValidPhoneNumber,
  formatIncompletePhoneNumber,
} from 'libphonenumber-js';

/**
 * Validates that a field is not empty.
 */
export function validateRequired(
  value: string,
  message = 'This field is required'
): string | null {
  if (!value || value.trim().length === 0) {
    return message;
  }
  return null;
}

/**
 * Validates email address format.
 */
export function validateEmail(
  value: string,
  message = 'Please enter a valid email address'
): string | null {
  if (!value || value.trim().length === 0) return null; // Let validateRequired handle required validation

  // Basic email regex that covers most common cases
  const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

  // Additional checks for invalid patterns
  if (
    value.includes('..') ||
    value.includes(' ') ||
    value.startsWith('@') ||
    value.endsWith('@') ||
    value.startsWith('.') ||
    value.endsWith('.') ||
    !emailRegex.test(value)
  ) {
    return message;
  }

  return null;
}

/**
 * Validates phone number format using libphonenumber-js for international support.
 * Attempts to parse the phone number and validates it according to international standards.
 * Uses Australia as the default country for national numbers.
 */
export function validatePhone(
  value: string,
  message = 'Please enter a valid phone number'
): string | null {
  if (!value || value.trim().length === 0) return null; // Let validateRequired handle required validation

  // First try to validate as international number (if it starts with +)
  if (value.trim().startsWith('+')) {
    const isValid = isValidPhoneNumber(value);
    return isValid ? null : message;
  }

  // For national numbers, use Australia as default country
  const isValid = isValidPhoneNumber(value, 'AU');
  return isValid ? null : message;
}

/**
 * Validates URL format (http/https only).
 */
export function validateUrl(
  value: string,
  message = 'Please enter a valid URL'
): string | null {
  if (!value || value.trim().length === 0) return null; // Let validateRequired handle required validation

  try {
    const url = new URL(value);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      return message;
    }
    // Additional check for valid hostname
    if (!url.hostname || url.hostname === '.') {
      return message;
    }
    return null;
  } catch {
    return message;
  }
}

/**
 * Formats a phone number for display using international standards.
 * Attempts to parse and format the number, falling back to the original value if parsing fails.
 * Uses Australia as the default country for national numbers.
 * Formats international numbers in international format, national numbers in national format.
 */
export function formatPhoneNumber(value: string): string {
  if (!value) return value;

  try {
    // If the input starts with +, treat as international
    if (value.trim().startsWith('+')) {
      const phoneNumber = parsePhoneNumberFromString(value);
      if (phoneNumber && phoneNumber.isValid()) {
        return phoneNumber.formatInternational();
      }
    } else {
      // For national numbers, use Australia as default country
      const phoneNumber = parsePhoneNumberFromString(value, 'AU');
      if (phoneNumber && phoneNumber.isValid()) {
        return phoneNumber.formatNational();
      }
    }
  } catch {
    // If parsing fails, fall back to original value
  }

  // If no valid phone number could be parsed, return original value
  return value;
}

/**
 * Normalizes a phone number to E.164 format (international standard).
 * Returns the phone number in E.164 format if valid, otherwise returns the original value.
 * Uses Australia as the default country for national numbers.
 */
export function normalizePhoneNumber(value: string): string {
  if (!value) return value;

  try {
    // If the input starts with +, treat as international
    if (value.trim().startsWith('+')) {
      const phoneNumber = parsePhoneNumberFromString(value);
      if (phoneNumber && phoneNumber.isValid()) {
        return phoneNumber.number;
      }
    } else {
      // For national numbers, use Australia as default country
      const phoneNumber = parsePhoneNumberFromString(value, 'AU');
      if (phoneNumber && phoneNumber.isValid()) {
        return phoneNumber.number;
      }
    }
  } catch {
    // If parsing fails, fall back to original value
  }

  // If no valid phone number could be parsed, return original value
  return value;
}

/**
 * Formats an incomplete phone number as the user types.
 * Useful for real-time formatting in input fields.
 */
export function formatIncompletePhone(value: string): string {
  if (!value) return value;

  try {
    // Use libphonenumber-js to format incomplete numbers
    return formatIncompletePhoneNumber(value);
  } catch {
    // If formatting fails, return original value
    return value;
  }
}

/**
 * Creates a validation function that combines multiple validators.
 */
export function combineValidators(
  ...validators: Array<(value: string) => string | null>
) {
  return (value: string): string | null => {
    for (const validator of validators) {
      const error = validator(value);
      if (error) return error;
    }
    return null;
  };
}

/**
 * Creates a validation function for required email fields.
 */
export function validateRequiredEmail(value: string): string | null {
  return combineValidators(validateRequired, validateEmail)(value);
}

/**
 * Creates a validation function for required phone fields.
 */
export function validateRequiredPhone(value: string): string | null {
  return combineValidators(validateRequired, validatePhone)(value);
}

/**
 * Creates a validation function for required URL fields.
 */
export function validateRequiredUrl(value: string): string | null {
  return combineValidators(validateRequired, validateUrl)(value);
}
