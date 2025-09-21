/**
 * Tests for relationship validation functions.
 */

import {
  validateRelationshipType,
  validateContactId,
  validateNotSelfRelationship,
  validateRequiredRelationshipType,
  validateRequiredContactId,
  validateRelationshipForm,
} from '../validation';
import { RelationshipType } from '@/types/contacts';

describe('validateRelationshipType', () => {
  it('should return null for valid relationship types', () => {
    expect(validateRelationshipType(RelationshipType.FRIEND)).toBeNull();
    expect(validateRelationshipType(RelationshipType.PARENT)).toBeNull();
    expect(validateRelationshipType(RelationshipType.COLLEAGUE)).toBeNull();
  });

  it('should return null for empty values', () => {
    expect(validateRelationshipType('')).toBeNull();
    expect(validateRelationshipType('   ')).toBeNull();
  });

  it('should return error for invalid relationship types', () => {
    expect(validateRelationshipType('invalid')).toBe(
      'Please select a valid relationship type'
    );
    expect(validateRelationshipType('INVALID')).toBe(
      'Please select a valid relationship type'
    );
    expect(validateRelationshipType('123')).toBe(
      'Please select a valid relationship type'
    );
  });

  it('should use custom error message', () => {
    const customMessage = 'Custom error message';
    expect(validateRelationshipType('invalid', customMessage)).toBe(
      customMessage
    );
  });
});

describe('validateContactId', () => {
  it('should return null for valid contact IDs', () => {
    expect(validateContactId(1)).toBeNull();
    expect(validateContactId(123)).toBeNull();
    expect(validateContactId('1')).toBeNull();
    expect(validateContactId('123')).toBeNull();
  });

  it('should return null for empty values', () => {
    expect(validateContactId('')).toBeNull();
    expect(validateContactId(null as any)).toBeNull();
    expect(validateContactId(undefined as any)).toBeNull();
  });

  it('should return error for invalid contact IDs', () => {
    expect(validateContactId(0)).toBe('Please select a valid contact');
    expect(validateContactId(-1)).toBe('Please select a valid contact');
    expect(validateContactId(1.5)).toBe('Please select a valid contact');
    expect(validateContactId('0')).toBe('Please select a valid contact');
    expect(validateContactId('-1')).toBe('Please select a valid contact');
    expect(validateContactId('abc')).toBe('Please select a valid contact');
    expect(validateContactId('1.5')).toBe('Please select a valid contact');
  });

  it('should use custom error message', () => {
    const customMessage = 'Custom error message';
    expect(validateContactId(0, customMessage)).toBe(customMessage);
  });
});

describe('validateNotSelfRelationship', () => {
  it('should return null for different contact IDs', () => {
    expect(validateNotSelfRelationship(1, 2)).toBeNull();
    expect(validateNotSelfRelationship('1', '2')).toBeNull();
    expect(validateNotSelfRelationship(1, '2')).toBeNull();
    expect(validateNotSelfRelationship('1', 2)).toBeNull();
  });

  it('should return null for empty values', () => {
    expect(validateNotSelfRelationship('', '')).toBeNull();
    expect(validateNotSelfRelationship(null as any, null as any)).toBeNull();
    expect(validateNotSelfRelationship(1, '')).toBeNull();
    expect(validateNotSelfRelationship('', 1)).toBeNull();
  });

  it('should return error for same contact IDs', () => {
    expect(validateNotSelfRelationship(1, 1)).toBe(
      'A contact cannot have a relationship with themselves'
    );
    expect(validateNotSelfRelationship('1', '1')).toBe(
      'A contact cannot have a relationship with themselves'
    );
    expect(validateNotSelfRelationship(1, '1')).toBe(
      'A contact cannot have a relationship with themselves'
    );
    expect(validateNotSelfRelationship('1', 1)).toBe(
      'A contact cannot have a relationship with themselves'
    );
  });

  it('should use custom error message', () => {
    const customMessage = 'Custom error message';
    expect(validateNotSelfRelationship(1, 1, customMessage)).toBe(
      customMessage
    );
  });
});

describe('validateRequiredRelationshipType', () => {
  it('should return error for empty values', () => {
    expect(validateRequiredRelationshipType('')).toBe('This field is required');
    expect(validateRequiredRelationshipType('   ')).toBe(
      'This field is required'
    );
  });

  it('should return null for valid relationship types', () => {
    expect(
      validateRequiredRelationshipType(RelationshipType.FRIEND)
    ).toBeNull();
  });

  it('should return error for invalid relationship types', () => {
    expect(validateRequiredRelationshipType('invalid')).toBe(
      'Please select a valid relationship type'
    );
  });
});

describe('validateRequiredContactId', () => {
  it('should return error for empty values', () => {
    expect(validateRequiredContactId('')).toBe('This field is required');
    expect(validateRequiredContactId(0)).toBe('This field is required');
    expect(validateRequiredContactId(null as any)).toBe(
      'This field is required'
    );
    expect(validateRequiredContactId(undefined as any)).toBe(
      'This field is required'
    );
  });

  it('should return null for valid contact IDs', () => {
    expect(validateRequiredContactId(1)).toBeNull();
    expect(validateRequiredContactId('123')).toBeNull();
  });

  it('should return error for invalid contact IDs', () => {
    expect(validateRequiredContactId(-1)).toBe('Please select a valid contact');
    expect(validateRequiredContactId('abc')).toBe(
      'Please select a valid contact'
    );
  });
});

describe('validateRelationshipForm', () => {
  it('should return no errors for valid form data', () => {
    const data = {
      from_contact_id: 1,
      to_contact_id: 2,
      relationship_type: RelationshipType.FRIEND,
    };

    const errors = validateRelationshipForm(data);

    expect(errors.from_contact_id).toBeNull();
    expect(errors.to_contact_id).toBeNull();
    expect(errors.relationship_type).toBeNull();
  });

  it('should return errors for empty required fields', () => {
    const data = {
      from_contact_id: '',
      to_contact_id: '',
      relationship_type: '',
    };

    const errors = validateRelationshipForm(data);

    expect(errors.from_contact_id).toBe('This field is required');
    expect(errors.to_contact_id).toBe('This field is required');
    expect(errors.relationship_type).toBe('This field is required');
  });

  it('should return errors for invalid field values', () => {
    const data = {
      from_contact_id: -1,
      to_contact_id: 'abc',
      relationship_type: 'invalid',
    };

    const errors = validateRelationshipForm(data);

    expect(errors.from_contact_id).toBe('Please select a valid contact');
    expect(errors.to_contact_id).toBe('Please select a valid contact');
    expect(errors.relationship_type).toBe(
      'Please select a valid relationship type'
    );
  });

  it('should return error for self-relationship', () => {
    const data = {
      from_contact_id: 1,
      to_contact_id: 1,
      relationship_type: RelationshipType.FRIEND,
    };

    const errors = validateRelationshipForm(data);

    expect(errors.from_contact_id).toBeNull();
    expect(errors.to_contact_id).toBe(
      'A contact cannot have a relationship with themselves'
    );
    expect(errors.relationship_type).toBeNull();
  });

  it('should not check self-relationship if contact IDs are invalid', () => {
    const data = {
      from_contact_id: 'abc',
      to_contact_id: 'abc',
      relationship_type: RelationshipType.FRIEND,
    };

    const errors = validateRelationshipForm(data);

    expect(errors.from_contact_id).toBe('Please select a valid contact');
    expect(errors.to_contact_id).toBe('Please select a valid contact');
    expect(errors.relationship_type).toBeNull();
  });
});
