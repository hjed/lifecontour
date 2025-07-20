/**
 * @jest-environment jsdom
 */

import { renderHook } from '@testing-library/react';
import { useDisplayContacts } from '../useDisplayContacts';
import { contactTestUtils } from '@/test-utils';
import { ContactMethodType } from '../../types/contacts';

describe('useDisplayContacts', () => {
  const mockContact = contactTestUtils.createMockContact();

  // Create a contact with phone number for testing
  const mockContactWithPhone = contactTestUtils.createMockContact({
    attributes: {
      ...contactTestUtils.createMockContact().attributes,
      contact_methods: [
        {
          id: '1',
          type: 'contact_methods' as const,
          attributes: {
            method_type: ContactMethodType.EMAIL,
            value: 'john@example.com',
            label: 'Work',
            is_primary: true,
          },
        },
        {
          id: '2',
          type: 'contact_methods' as const,
          attributes: {
            method_type: ContactMethodType.PHONE,
            value: '+1-555-123-4567',
            label: 'Mobile',
            is_primary: true,
          },
        },
      ],
    },
  });

  const mockContactWithHighlighting = {
    ...mockContactWithPhone,
    meta: {
      highlighted: {
        first_name: '<mark>John</mark>',
        last_name: '<mark>Doe</mark>',
        email: '<mark>john</mark>@example.com',
        phone: '+1-555-<mark>123</mark>-4567',
      },
    },
  };

  it('transforms basic contact data correctly', () => {
    const { result } = renderHook(() => useDisplayContacts([mockContact]));

    expect(result.current).toHaveLength(1);
    const displayContact = result.current[0];

    expect(displayContact).toEqual({
      id: mockContact.id,
      name: 'John Doe',
      is_favourite: false,
      primary_email: 'john@example.com',
      primary_phone: undefined, // Mock contact doesn't have phone
      tags: [],
      created_at: mockContact.attributes.created_at,
      updated_at: mockContact.attributes.updated_at,
      highlighted: undefined, // No meta field in basic contact
      isSearchResult: false,
      highlightedName: null,
      highlightedEmail: null,
      highlightedPhone: null,
    });
  });

  it('handles undefined contacts', () => {
    const { result } = renderHook(() => useDisplayContacts(undefined));
    expect(result.current).toEqual([]);
  });

  it('handles empty contacts array', () => {
    const { result } = renderHook(() => useDisplayContacts([]));
    expect(result.current).toEqual([]);
  });

  it('handles contact without last name', () => {
    const contactWithoutLastName = {
      ...mockContact,
      attributes: {
        ...mockContact.attributes,
        last_name: undefined,
      },
    };

    const { result } = renderHook(() =>
      useDisplayContacts([contactWithoutLastName])
    );
    expect(result.current[0].name).toBe('John');
  });

  it('handles contact without contact methods', () => {
    const contactWithoutMethods = {
      ...mockContact,
      attributes: {
        ...mockContact.attributes,
        contact_methods: [],
      },
    };

    const { result } = renderHook(() =>
      useDisplayContacts([contactWithoutMethods])
    );
    const displayContact = result.current[0];

    expect(displayContact.primary_email).toBeUndefined();
    expect(displayContact.primary_phone).toBeUndefined();
  });

  it('finds primary email and phone correctly', () => {
    const contactWithMultipleMethods = {
      ...mockContact,
      attributes: {
        ...mockContact.attributes,
        contact_methods: [
          {
            id: '1',
            type: 'contact_methods' as const,
            attributes: {
              method_type: ContactMethodType.EMAIL,
              value: 'secondary@example.com',
              is_primary: false,
            },
          },
          {
            id: '2',
            type: 'contact_methods' as const,
            attributes: {
              method_type: ContactMethodType.EMAIL,
              value: 'primary@example.com',
              is_primary: true,
            },
          },
          {
            id: '3',
            type: 'contact_methods' as const,
            attributes: {
              method_type: ContactMethodType.PHONE,
              value: '+1-555-999-8888',
              is_primary: true,
            },
          },
        ],
      },
    };

    const { result } = renderHook(() =>
      useDisplayContacts([contactWithMultipleMethods])
    );
    const displayContact = result.current[0];

    expect(displayContact.primary_email).toBe('primary@example.com');
    expect(displayContact.primary_phone).toBe('+1-555-999-8888');
  });

  it('handles search highlighting when shouldUseSearch is true', () => {
    const { result } = renderHook(() =>
      useDisplayContacts([mockContactWithHighlighting], true)
    );

    const displayContact = result.current[0];

    expect(displayContact.isSearchResult).toBe(true);
    expect(displayContact.highlighted).toEqual({
      first_name: '<mark>John</mark>',
      last_name: '<mark>Doe</mark>',
      email: '<mark>john</mark>@example.com',
      phone: '+1-555-<mark>123</mark>-4567',
    });
    expect(displayContact.highlightedName).toBe(
      '<mark>John</mark> <mark>Doe</mark>'
    );
    expect(displayContact.highlightedEmail).toBe(
      '<mark>john</mark>@example.com'
    );
    expect(displayContact.highlightedPhone).toBe(
      '+1-555-<mark>123</mark>-4567'
    );
  });

  it('does not include search highlighting when shouldUseSearch is false', () => {
    const { result } = renderHook(() =>
      useDisplayContacts([mockContactWithHighlighting], false)
    );

    const displayContact = result.current[0];

    expect(displayContact.isSearchResult).toBe(false);
    expect(displayContact.highlighted).toEqual({
      first_name: '<mark>John</mark>',
      last_name: '<mark>Doe</mark>',
      email: '<mark>john</mark>@example.com',
      phone: '+1-555-<mark>123</mark>-4567',
    });
    expect(displayContact.highlightedName).toBeNull();
    expect(displayContact.highlightedEmail).toBeNull();
    expect(displayContact.highlightedPhone).toBeNull();
  });

  it('handles contact with highlighting but missing highlighted fields', () => {
    const contactWithPartialHighlighting = {
      ...mockContact,
      meta: {
        highlighted: {
          first_name: '<mark>John</mark>',
          // Missing last_name, email, phone
        },
      },
    };

    const { result } = renderHook(() =>
      useDisplayContacts([contactWithPartialHighlighting], true)
    );

    const displayContact = result.current[0];

    expect(displayContact.isSearchResult).toBe(true);
    expect(displayContact.highlightedName).toBe('<mark>John</mark> Doe');
    expect(displayContact.highlightedEmail).toBeNull();
    expect(displayContact.highlightedPhone).toBeNull();
  });

  it('handles contact without meta.highlighted when shouldUseSearch is true', () => {
    const { result } = renderHook(() =>
      useDisplayContacts([mockContact], true)
    );

    const displayContact = result.current[0];

    expect(displayContact.isSearchResult).toBe(false);
    expect(displayContact.highlighted).toBeUndefined(); // No meta field
    expect(displayContact.highlightedName).toBeNull();
    expect(displayContact.highlightedEmail).toBeNull();
    expect(displayContact.highlightedPhone).toBeNull();
  });

  it('updates when dependencies change', () => {
    const { result, rerender } = renderHook(
      ({ contacts, shouldUseSearch }) =>
        useDisplayContacts(contacts, shouldUseSearch),
      {
        initialProps: { contacts: [mockContact], shouldUseSearch: false },
      }
    );

    const firstResult = result.current;
    expect(firstResult[0].isSearchResult).toBe(false);

    // Rerender with different shouldUseSearch - should update the result
    rerender({
      contacts: [mockContactWithHighlighting],
      shouldUseSearch: true,
    });
    expect(result.current[0].isSearchResult).toBe(true);
    expect(result.current[0].highlightedName).toBe(
      '<mark>John</mark> <mark>Doe</mark>'
    );

    // Rerender back to original - should update again
    rerender({ contacts: [mockContact], shouldUseSearch: false });
    expect(result.current[0].isSearchResult).toBe(false);
  });
});
