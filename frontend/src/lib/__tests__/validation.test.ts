/**
 * Tests for field validation utilities.
 *
 * Tests validation functions for different field types including
 * email, phone, URL validation and formatting utilities.
 */

import {
  validateEmail,
  validatePhone,
  validateUrl,
  validateRequired,
  formatPhoneNumber,
  normalizePhoneNumber,
} from '@/lib/validation';

describe('validation utilities', () => {
  describe('validateRequired', () => {
    it('should return error for empty string', () => {
      expect(validateRequired('')).toBe('This field is required');
    });

    it('should return error for whitespace only', () => {
      expect(validateRequired('   ')).toBe('This field is required');
    });

    it('should return null for valid value', () => {
      expect(validateRequired('valid value')).toBeNull();
    });

    it('should use custom message when provided', () => {
      expect(validateRequired('', 'Name is required')).toBe('Name is required');
    });
  });

  describe('validateEmail', () => {
    it('should validate correct email addresses', () => {
      const validEmails = [
        'test@example.com',
        'user.name@domain.co.uk',
        'user+tag@example.org',
        'user123@test-domain.com',
        'a@b.co',
      ];

      validEmails.forEach(email => {
        expect(validateEmail(email)).toBeNull();
      });
    });

    it('should reject invalid email addresses', () => {
      const invalidEmails = [
        'invalid-email',
        '@example.com',
        'user@',
        'user..name@example.com',
        'user@.com',
        'user@domain.',
        'user name@example.com',
      ];

      invalidEmails.forEach(email => {
        expect(validateEmail(email)).toBe('Please enter a valid email address');
      });
    });

    it('should return null for empty values', () => {
      expect(validateEmail('')).toBeNull();
      expect(validateEmail('   ')).toBeNull();
    });

    it('should use custom message when provided', () => {
      expect(validateEmail('invalid', 'Email format is wrong')).toBe(
        'Email format is wrong'
      );
    });
  });

  describe('validatePhone', () => {
    it('should validate Australian phone numbers', () => {
      const validPhones = [
        '+61 2 1234 5678',
        '02 1234 5678',
        '0412 345 678',
        '+61412345678',
        '(02) 1234 5678',
        '02-1234-5678',
        '1300 123 456',
        '13 12 34',
      ];

      validPhones.forEach(phone => {
        expect(validatePhone(phone)).toBeNull();
      });
    });

    it('should validate international phone numbers', () => {
      const validPhones = [
        '+1 555 123 4567',
        '+44 20 7123 4567',
        '+33 1 23 45 67 89',
      ];

      validPhones.forEach(phone => {
        expect(validatePhone(phone)).toBeNull();
      });
    });

    it('should reject invalid phone numbers', () => {
      const invalidPhones = [
        '123',
        'abc123',
        '++61 2 1234 5678',
        '61 2 1234 5678', // Missing +
      ];

      invalidPhones.forEach(phone => {
        expect(validatePhone(phone)).toBe('Please enter a valid phone number');
      });
    });

    it('should return null for empty values', () => {
      expect(validatePhone('')).toBeNull();
      expect(validatePhone('   ')).toBeNull();
    });

    it('should use custom message when provided', () => {
      expect(validatePhone('123', 'Phone format is wrong')).toBe(
        'Phone format is wrong'
      );
    });
  });

  describe('validateUrl', () => {
    it('should validate correct URLs', () => {
      const validUrls = [
        'https://example.com',
        'http://test.org',
        'https://www.example.com/path',
        'https://example.com:8080',
        'https://sub.domain.example.com',
        'https://example.com/path?query=value',
        'https://example.com/path#fragment',
      ];

      validUrls.forEach(url => {
        expect(validateUrl(url)).toBeNull();
      });
    });

    it('should reject invalid URLs', () => {
      const invalidUrls = [
        'not-a-url',
        'ftp://example.com', // Only http/https allowed
        'example.com', // Missing protocol
        'https://',
        'https://.',
      ];

      invalidUrls.forEach(url => {
        expect(validateUrl(url)).toBe('Please enter a valid URL');
      });
    });

    it('should return null for empty values', () => {
      expect(validateUrl('')).toBeNull();
      expect(validateUrl('   ')).toBeNull();
    });

    it('should use custom message when provided', () => {
      expect(validateUrl('invalid', 'URL format is wrong')).toBe(
        'URL format is wrong'
      );
    });
  });

  describe('formatPhoneNumber', () => {
    it('should format Australian mobile numbers', () => {
      expect(formatPhoneNumber('0412345678')).toBe('0412 345 678');
      expect(formatPhoneNumber('+61412345678')).toBe('+61 412 345 678');
    });

    it('should format Australian landline numbers', () => {
      expect(formatPhoneNumber('0212345678')).toBe('02 1234 5678');
      expect(formatPhoneNumber('+61212345678')).toBe('+61 2 1234 5678');
    });

    it('should format 1300/1800 numbers', () => {
      expect(formatPhoneNumber('1300123456')).toBe('1300 123 456');
      expect(formatPhoneNumber('1800123456')).toBe('1800 123 456');
    });

    it('should handle already formatted numbers', () => {
      expect(formatPhoneNumber('0412 345 678')).toBe('0412 345 678');
      expect(formatPhoneNumber('+61 2 1234 5678')).toBe('+61 2 1234 5678');
    });

    it('should return original for invalid numbers', () => {
      expect(formatPhoneNumber('123')).toBe('123');
      expect(formatPhoneNumber('abc')).toBe('abc');
    });
  });

  describe('normalizePhoneNumber', () => {
    it('should remove formatting from phone numbers', () => {
      expect(normalizePhoneNumber('0412 345 678')).toBe('0412345678');
      expect(normalizePhoneNumber('+61 2 1234 5678')).toBe('+61212345678');
      expect(normalizePhoneNumber('(02) 1234-5678')).toBe('0212345678');
    });

    it('should handle already normalized numbers', () => {
      expect(normalizePhoneNumber('0412345678')).toBe('0412345678');
      expect(normalizePhoneNumber('+61412345678')).toBe('+61412345678');
    });

    it('should preserve international prefix', () => {
      expect(normalizePhoneNumber('+1 555 123 4567')).toBe('+15551234567');
      expect(normalizePhoneNumber('+44 20 7123 4567')).toBe('+442071234567');
    });
  });
});
