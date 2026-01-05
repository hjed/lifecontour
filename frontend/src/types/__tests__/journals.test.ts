/**
 * Tests for journal types to ensure they match backend API schemas.
 */

import {
  JournalType,
  JournalContactRelationshipType,
  JournalAttributes,
  JournalResource,
  JournalFilters,
  JournalFormData,
} from '../journals';

describe('Journal Types', () => {
  describe('JournalType enum', () => {
    it('should have all expected journal types', () => {
      expect(JournalType.NOTE).toBe('NOTE');
      expect(JournalType.EVENT).toBe('EVENT');
      expect(JournalType.MOOD_RATING).toBe('MOOD_RATING');
      expect(JournalType.PLAN).toBe('PLAN');
      expect(JournalType.TRAVEL).toBe('TRAVEL');
      expect(JournalType.PHOTO_ALBUM).toBe('PHOTO_ALBUM');
    });
  });

  describe('JournalContactRelationshipType enum', () => {
    it('should have all expected relationship types', () => {
      expect(JournalContactRelationshipType.PARTICIPANT).toBe('PARTICIPANT');
      expect(JournalContactRelationshipType.INVITEE).toBe('INVITEE');
      expect(JournalContactRelationshipType.MENTION).toBe('MENTION');
      expect(JournalContactRelationshipType.ABOUT).toBe('ABOUT');
    });
  });

  describe('JournalAttributes', () => {
    it('should create valid journal attributes', () => {
      const attributes: JournalAttributes = {
        title: 'Test Journal',
        content: 'Test content',
        event_date_range: {
          start: '2024-01-01',
          end: '2024-01-01',
        },
        types: [JournalType.NOTE],
        tags: [],
        contacts: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };

      expect(attributes.title).toBe('Test Journal');
      expect(attributes.types).toContain(JournalType.NOTE);
    });

    it('should support multiple types', () => {
      const attributes: JournalAttributes = {
        title: 'Multi-type Journal',
        content: 'Content',
        event_date_range: {
          start: '2024-01-01',
          end: '2024-01-02',
        },
        types: [JournalType.NOTE, JournalType.EVENT],
        tags: [],
        contacts: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };

      expect(attributes.types).toHaveLength(2);
      expect(attributes.types).toContain(JournalType.NOTE);
      expect(attributes.types).toContain(JournalType.EVENT);
    });

    it('should support optional calendar', () => {
      const attributes: JournalAttributes = {
        title: 'Journal with Calendar',
        content: 'Content',
        event_date_range: {
          start: '2024-01-01',
          end: '2024-01-01',
        },
        types: [JournalType.EVENT],
        tags: [],
        contacts: [],
        calendar: {
          id: 'cal-1',
          name: 'Personal',
          color: '#FF0000',
        },
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      };

      expect(attributes.calendar?.id).toBe('cal-1');
      expect(attributes.calendar?.color).toBe('#FF0000');
    });
  });

  describe('JournalResource', () => {
    it('should create valid journal resource', () => {
      const journal: JournalResource = {
        type: 'journals',
        id: '1',
        attributes: {
          title: 'Test Journal',
          content: 'Content',
          event_date_range: {
            start: '2024-01-01',
            end: '2024-01-01',
          },
          types: [JournalType.NOTE],
          tags: [],
          contacts: [],
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      };

      expect(journal.type).toBe('journals');
      expect(journal.id).toBe('1');
      expect(journal.attributes.title).toBe('Test Journal');
    });
  });

  describe('JournalFilters', () => {
    it('should support all filter options', () => {
      const filters: JournalFilters = {
        search: 'test',
        types: [JournalType.NOTE, JournalType.EVENT],
        contact_id: 'contact-1',
        tag_ids: ['tag-1', 'tag-2'],
        calendar_id: 'cal-1',
        date_from: '2024-01-01',
        date_to: '2024-12-31',
        page: 1,
        limit: 20,
      };

      expect(filters.search).toBe('test');
      expect(filters.types).toHaveLength(2);
      expect(filters.contact_id).toBe('contact-1');
      expect(filters.tag_ids).toHaveLength(2);
    });

    it('should allow all filters to be optional', () => {
      const filters: JournalFilters = {};

      expect(filters.search).toBeUndefined();
      expect(filters.types).toBeUndefined();
    });
  });

  describe('JournalFormData', () => {
    it('should create valid form data', () => {
      const formData: JournalFormData = {
        title: 'New Journal',
        content: 'Content',
        event_date_range: {
          start: '2024-01-01',
          end: '2024-01-01',
        },
      };

      expect(formData.title).toBe('New Journal');
      expect(formData.event_date_range.start).toBe('2024-01-01');
    });
  });
});
