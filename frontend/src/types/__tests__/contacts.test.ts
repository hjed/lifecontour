/**
 * Tests for contact types to ensure they match backend API schemas.
 */

import {
  ContactAttributes,
  ContactFilters,
  ContactResource,
  TagResource,
} from '../contacts';

describe('Contact Types', () => {
  describe('ContactAttributes', () => {
    it('should include is_favourite field', () => {
      const contactAttributes: ContactAttributes = {
        first_name: 'John',
        last_name: 'Doe',
        is_favourite: true,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        contact_methods: [],
        addresses: [],
        notes: [],
      };

      expect(contactAttributes.is_favourite).toBe(true);
    });

    it('should have is_favourite as optional with default false', () => {
      const contactAttributes: ContactAttributes = {
        first_name: 'Jane',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        contact_methods: [],
        addresses: [],
        notes: [],
      };

      // Should be able to create without is_favourite
      expect(contactAttributes.first_name).toBe('Jane');
    });
  });

  describe('ContactFilters', () => {
    it('should include favourite filter option', () => {
      const filters: ContactFilters = {
        search: 'john',
        tags: ['1', '2'],
        favourite: true,
        created_after: '2024-01-01',
        created_before: '2024-12-31',
      };

      expect(filters.favourite).toBe(true);
    });

    it('should allow favourite filter to be undefined', () => {
      const filters: ContactFilters = {
        search: 'john',
      };

      expect(filters.favourite).toBeUndefined();
    });

    it('should allow favourite filter to be false', () => {
      const filters: ContactFilters = {
        favourite: false,
      };

      expect(filters.favourite).toBe(false);
    });
  });

  describe('ContactResource', () => {
    it('should include is_favourite in attributes', () => {
      const contact: ContactResource = {
        type: 'contacts',
        id: '1',
        attributes: {
          first_name: 'John',
          last_name: 'Doe',
          is_favourite: true,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
          contact_methods: [],
          addresses: [],
          notes: [],
        },
      };

      expect(contact.attributes.is_favourite).toBe(true);
    });
  });

  describe('TagResource', () => {
    it('should have proper structure for sidebar navigation', () => {
      const tag: TagResource = {
        type: 'tags',
        id: '1',
        attributes: {
          name: 'Work',
          color: '#3182CE',
          description: 'Work contacts',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      };

      expect(tag.attributes.name).toBe('Work');
      expect(tag.attributes.color).toBe('#3182CE');
    });
  });
});
