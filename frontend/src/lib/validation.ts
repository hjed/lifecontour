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

import { RelationshipType } from '@/types/contacts';

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

/**
 * Validates that a relationship type is valid.
 */
export function validateRelationshipType(
  value: string,
  message = 'Please select a valid relationship type'
): string | null {
  if (!value || value.trim().length === 0) return null; // Let validateRequired handle required validation

  if (!Object.values(RelationshipType).includes(value as RelationshipType)) {
    return message;
  }

  return null;
}

/**
 * Helper function to validate a numeric value is a positive integer.
 */
function isValidPositiveInteger(value: number): boolean {
  return !isNaN(value) && value > 0 && Number.isInteger(value);
}

/**
 * Validates that a contact ID is valid (positive integer).
 */
export function validateContactId(
  value: number | string,
  message = 'Please select a valid contact'
): string | null {
  if (value === null || value === undefined || value === '') return null; // Let validateRequired handle required validation

  // For string values, check if it's a valid integer string first
  if (typeof value === 'string') {
    // Check if the string contains only digits (and optional leading/trailing whitespace)
    if (!/^\s*\d+\s*$/.test(value)) {
      return message;
    }
    const numValue = parseInt(value.trim(), 10);
    if (!isValidPositiveInteger(numValue)) {
      return message;
    }
  } else {
    // For number values, check if it's a positive integer (including rejecting zero)
    if (!isValidPositiveInteger(value)) {
      return message;
    }
  }

  return null;
}

/**
 * Validates that a relationship doesn't create a self-reference.
 */
export function validateNotSelfRelationship(
  fromContactId: number | string,
  toContactId: number | string,
  message = 'A contact cannot have a relationship with themselves'
): string | null {
  if (!fromContactId || !toContactId) return null; // Let other validators handle empty values

  const fromId =
    typeof fromContactId === 'string'
      ? parseInt(fromContactId, 10)
      : fromContactId;
  const toId =
    typeof toContactId === 'string' ? parseInt(toContactId, 10) : toContactId;

  if (fromId === toId) {
    return message;
  }

  return null;
}

/**
 * Creates a validation function for required relationship type fields.
 */
export function validateRequiredRelationshipType(value: string): string | null {
  return combineValidators(validateRequired, validateRelationshipType)(value);
}

/**
 * Creates a validation function for required contact ID fields.
 */
export function validateRequiredContactId(
  value: number | string
): string | null {
  // Check required first - handle both string and number types
  if (value === null || value === undefined || value === '' || value === 0) {
    return 'This field is required';
  }

  // Then validate the contact ID
  return validateContactId(value);
}

/**
 * Validates a complete relationship form data object.
 */
export function validateRelationshipForm(data: {
  from_contact_id: number | string;
  to_contact_id: number | string;
  relationship_type: string;
}): Record<string, string | null> {
  const errors: Record<string, string | null> = {};

  // Validate from_contact_id
  errors.from_contact_id = validateRequiredContactId(data.from_contact_id);

  // Validate to_contact_id
  errors.to_contact_id = validateRequiredContactId(data.to_contact_id);

  // Validate relationship_type
  errors.relationship_type = validateRequiredRelationshipType(
    data.relationship_type
  );

  // Validate not self-relationship (only if both IDs are valid)
  if (!errors.from_contact_id && !errors.to_contact_id) {
    const selfRelationshipError = validateNotSelfRelationship(
      data.from_contact_id,
      data.to_contact_id
    );
    if (selfRelationshipError) {
      errors.to_contact_id = selfRelationshipError;
    }
  }

  return errors;
}
