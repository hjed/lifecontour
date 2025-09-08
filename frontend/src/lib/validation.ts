/**
 * Field validation utilities.
 *
 * Provides validation functions for different field types including
 * email, phone, URL validation and formatting utilities.
 * Follows Australian conventions where applicable.
 */

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
 * Validates phone number format (Australian and international).
 */
export function validatePhone(
  value: string,
  message = 'Please enter a valid phone number'
): string | null {
  if (!value || value.trim().length === 0) return null; // Let validateRequired handle required validation

  // Remove all non-digit characters except + for international numbers
  const cleaned = value.replace(/[^\d+]/g, '');

  // Check for valid patterns
  const patterns = [
    /^\+61[2-9]\d{8}$/, // Australian landline with country code
    /^\+61[4-5]\d{8}$/, // Australian mobile with country code
    /^\+61[13]\d{7,9}$/, // Australian special numbers (1300, 1800, 13xx) with country code
    /^0[2-9]\d{8}$/, // Australian landline
    /^0[4-5]\d{8}$/, // Australian mobile
    /^1[38]00\d{6}$/, // 1300/1800 numbers
    /^13\d{4}$/, // 13xx numbers
    /^\+\d{7,15}$/, // International numbers (7-15 digits after +)
  ];

  const isValid = patterns.some(pattern => pattern.test(cleaned));

  if (!isValid) {
    return message;
  }

  return null;
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
 * Formats a phone number for display (Australian format).
 */
export function formatPhoneNumber(value: string): string {
  if (!value) return value;

  // Remove all non-digit characters except +
  const cleaned = value.replace(/[^\d+]/g, '');

  // Australian mobile with country code: +61 4xx xxx xxx
  if (/^\+61[4-5]\d{8}$/.test(cleaned)) {
    return cleaned.replace(
      /^\+61([4-5])(\d{2})(\d{3})(\d{3})$/,
      '+61 $1$2 $3 $4'
    );
  }

  // Australian landline with country code: +61 x xxxx xxxx
  if (/^\+61[2-9]\d{8}$/.test(cleaned)) {
    return cleaned.replace(/^\+61([2-9])(\d{4})(\d{4})$/, '+61 $1 $2 $3');
  }

  // Australian mobile: 04xx xxx xxx
  if (/^0[4-5]\d{8}$/.test(cleaned)) {
    return cleaned.replace(/^(0[4-5]\d{2})(\d{3})(\d{3})$/, '$1 $2 $3');
  }

  // Australian landline: 0x xxxx xxxx
  if (/^0[2-9]\d{8}$/.test(cleaned)) {
    return cleaned.replace(/^(0[2-9])(\d{4})(\d{4})$/, '$1 $2 $3');
  }

  // 1300/1800 numbers: 1xxx xxx xxx
  if (/^1[38]00\d{6}$/.test(cleaned)) {
    return cleaned.replace(/^(1[38]00)(\d{3})(\d{3})$/, '$1 $2 $3');
  }

  // 13xx numbers: 13 xx xx
  if (/^13\d{4}$/.test(cleaned)) {
    return cleaned.replace(/^(13)(\d{2})(\d{2})$/, '$1 $2 $3');
  }

  // If no pattern matches, return original value
  return value;
}

/**
 * Normalizes a phone number by removing formatting.
 */
export function normalizePhoneNumber(value: string): string {
  if (!value) return value;

  // Remove all non-digit characters except + at the beginning
  return value.replace(/(?!^\+)[^\d]/g, '');
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
