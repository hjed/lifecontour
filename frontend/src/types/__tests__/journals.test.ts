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
  KayakingData,
  CrossCountrySkiingData,
} from '../journals';

describe('Journal Types', () => {
  describe('JournalType enum', () => {
    it('should have all expected journal types', () => {
      expect(JournalType.NOTE).toBe('note');
      expect(JournalType.EVENT).toBe('event');
      expect(JournalType.MOOD_RATING).toBe('mood_rating');
      expect(JournalType.PLAN).toBe('plan');
      expect(JournalType.TRAVEL).toBe('travel');
      expect(JournalType.PHOTO_ALBUM).toBe('photo_album');
      expect(JournalType.FITNESS).toBe('fitness');
      expect(JournalType.OUTDOOR_ACTIVITY).toBe('outdoor_activity');
      expect(JournalType.BUSHWALKING).toBe('bushwalking');
      expect(JournalType.JOGGING).toBe('jogging');
      expect(JournalType.ABSEILING_TRIP).toBe('abseiling_trip');
      expect(JournalType.CANYONING).toBe('canyoning');
      expect(JournalType.CLIMBING).toBe('climbing');
      expect(JournalType.KAYAKING).toBe('kayaking');
      expect(JournalType.CROSS_COUNTRY_SKIING).toBe('cross_country_skiing');
    });
  });

  describe('KayakingData interface', () => {
    it('should create valid kayaking data', () => {
      const data: KayakingData = {
        water_type: 'river',
      };

      expect(data.water_type).toBe('river');
    });

    it('should allow optional fields', () => {
      const data: KayakingData = {};

      expect(data.water_type).toBeUndefined();
    });
  });

  describe('CrossCountrySkiingData interface', () => {
    it('should create valid cross-country skiing data', () => {
      const data: CrossCountrySkiingData = {
        snow_conditions: 'packed powder',
      };

      expect(data.snow_conditions).toBe('packed powder');
    });

    it('should allow optional fields', () => {
      const data: CrossCountrySkiingData = {};

      expect(data.snow_conditions).toBeUndefined();
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
