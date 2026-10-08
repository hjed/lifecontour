import { SearchResultResource } from '@/types/search';
import { ContactResource } from '@/types/contacts';
import {
  groupSearchResults,
  transformSearchResultToDisplayJournal,
  extractContactRankingSignals,
} from '../searchUtils';

describe('searchUtils', () => {
  describe('groupSearchResults', () => {
    it('groups empty array into empty categories', () => {
      const result = groupSearchResults([]);
      expect(result).toEqual({ contacts: [], journals: [] });
    });

    it('groups contacts and journals correctly', () => {
      const mockContact: ContactResource = {
        type: 'contacts',
        id: 'contact-1',
        attributes: {
          first_name: 'John',
          last_name: 'Doe',
          created_at: '2024-01-01',
          updated_at: '2024-01-01',
          contact_methods: [],
          addresses: [],
          notes: [],
          relationships: [],
        },
      };

      const mockJournalSearchResult: SearchResultResource = {
        type: 'search-results',
        id: 'journal-1',
        attributes: {
          entity_type: 'journal',
          entity_id: '1',
          title: 'My Journal',
          content: 'Test content',
          score: 1.0,
          matched_terms: ['test'],
          created_at: '2024-01-01',
          updated_at: '2024-01-01',
        },
        meta: {
          original_id: '1',
          search_metadata: {},
        },
      };

      const mockOtherSearchResult: SearchResultResource = {
        type: 'search-results',
        id: 'calendar-1',
        attributes: {
          entity_type: 'calendar_event',
          entity_id: '1',
          title: 'My Event',
          content: 'Test event',
          score: 1.0,
          matched_terms: ['test'],
          created_at: '2024-01-01',
          updated_at: '2024-01-01',
        },
        meta: {
          original_id: '1',
          search_metadata: {},
        },
      };

      const results = [
        mockContact,
        mockJournalSearchResult,
        mockOtherSearchResult,
      ];

      const grouped = groupSearchResults(results);

      expect(grouped.contacts).toHaveLength(1);
      expect(grouped.contacts[0]).toBe(mockContact);

      expect(grouped.journals).toHaveLength(1);
      expect(grouped.journals[0]).toBe(mockJournalSearchResult);
    });
  });

  describe('transformSearchResultToDisplayJournal', () => {
    it('transforms SearchResultResource to DisplayJournal successfully with full metadata', () => {
      const mockResult: SearchResultResource = {
        type: 'search-results',
        id: 'journal-123',
        attributes: {
          entity_type: 'journal',
          entity_id: '123',
          title: 'My Test Journal',
          content: 'This is the journal content',
          highlighted_content: 'This is the <mark>journal</mark> content',
          score: 1.0,
          matched_terms: ['journal'],
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
        meta: {
          original_id: '123',
          search_metadata: {
            id: 123,
            user_id: 'user-1',
            title: 'My Test Journal',
            content: 'This is the journal content',
            event_date_range_start: '2024-02-01T10:00:00Z',
            event_date_range_end: '2024-02-01T11:00:00Z',
            types: ['NOTE', 'EVENT'],
            contact_ids: ['c1', 'c2'],
            tag_ids: ['t1'],
            calendar_id: 'cal1',
            parent_id: null,
            location: 'Test Location',
            entity_type: 'journal',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            _formatted: {
              title: 'My <mark>Test</mark> Journal',
              content: 'This is the <mark>journal</mark> content',
            },
          },
        },
      };

      const displayJournal = transformSearchResultToDisplayJournal(mockResult);

      expect(displayJournal.id).toBe('123');
      expect(displayJournal.title).toBe('My Test Journal');
      expect(displayJournal.content).toBe('This is the journal content');
      expect(displayJournal.event_date_range).toEqual({
        start: '2024-02-01T10:00:00Z',
        end: '2024-02-01T11:00:00Z',
      });
      expect(displayJournal.types).toEqual(['note', 'event']);
      expect(displayJournal.contacts.length).toBe(2);
      expect(displayJournal.contacts[0].id).toBe('c1');
      expect(displayJournal.tags.length).toBe(1);
      expect(displayJournal.tags[0].id).toBe('t1');
      expect(displayJournal.isSearchResult).toBe(true);
      expect(displayJournal.highlightedTitle).toBe(
        'My <mark>Test</mark> Journal'
      );
      expect(displayJournal.highlightedContent).toBe(
        'This is the <mark>journal</mark> content'
      );
    });

    it('handles missing metadata gracefully', () => {
      const mockResult: SearchResultResource = {
        type: 'search-results',
        id: 'journal-123',
        attributes: {
          entity_type: 'journal',
          entity_id: '123',
          title: 'Basic Journal',
          content: 'Basic content',
          score: 1.0,
          matched_terms: [],
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
        meta: {
          original_id: '123',
          search_metadata: {},
        },
      };

      const displayJournal = transformSearchResultToDisplayJournal(mockResult);

      expect(displayJournal.id).toBe('123');
      expect(displayJournal.title).toBe('Basic Journal');
      expect(displayJournal.content).toBe('Basic content');
      expect(displayJournal.types).toEqual(['note']); // Default
      expect(displayJournal.event_date_range).toEqual({
        start: '2024-01-01T00:00:00Z',
        end: '2024-01-01T00:00:00Z',
      });
    });
  });

  describe('extractContactRankingSignals', () => {
    it('extracts ranking signals from contact with full metadata', () => {
      const contact: ContactResource = {
        type: 'contacts',
        id: 'contact-1',
        attributes: {
          first_name: 'Alice',
          last_name: 'Ranking',
          created_at: '2024-01-01',
          updated_at: '2024-01-01',
          contact_methods: [],
          addresses: [],
          notes: [],
          relationships: [],
        },
        meta: {
          search_metadata: {
            is_favourite: true,
            has_summary: true,
            journal_count_30d: 5,
            activity_count_30d: 12,
            last_activity_date: '2024-06-15T10:00:00Z',
            relationships: ['Parent: Bob', 'Friend: Charlie'],
          },
        },
      };

      const signals = extractContactRankingSignals(contact);

      expect(signals.isFavourite).toBe(true);
      expect(signals.hasSummary).toBe(true);
      expect(signals.journalCount30d).toBe(5);
      expect(signals.activityCount30d).toBe(12);
      expect(signals.lastActivityDate).toBe('2024-06-15T10:00:00Z');
      expect(signals.relationships).toEqual(['Parent: Bob', 'Friend: Charlie']);
    });

    it('returns sensible defaults when metadata is missing', () => {
      const contact: ContactResource = {
        type: 'contacts',
        id: 'contact-2',
        attributes: {
          first_name: 'Bob',
          last_name: 'NoMeta',
          created_at: '2024-01-01',
          updated_at: '2024-01-01',
          contact_methods: [],
          addresses: [],
          notes: [],
          relationships: [],
        },
      };

      const signals = extractContactRankingSignals(contact);

      expect(signals.isFavourite).toBe(false);
      expect(signals.hasSummary).toBe(false);
      expect(signals.journalCount30d).toBe(0);
      expect(signals.activityCount30d).toBe(0);
      expect(signals.lastActivityDate).toBeNull();
      expect(signals.relationships).toEqual([]);
    });

    it('returns sensible defaults when search_metadata is empty object', () => {
      const contact: ContactResource = {
        type: 'contacts',
        id: 'contact-3',
        attributes: {
          first_name: 'Charlie',
          last_name: 'EmptyMeta',
          created_at: '2024-01-01',
          updated_at: '2024-01-01',
          contact_methods: [],
          addresses: [],
          notes: [],
          relationships: [],
        },
        meta: {
          search_metadata: {},
        },
      };

      const signals = extractContactRankingSignals(contact);

      expect(signals.isFavourite).toBe(false);
      expect(signals.hasSummary).toBe(false);
      expect(signals.journalCount30d).toBe(0);
      expect(signals.activityCount30d).toBe(0);
      expect(signals.lastActivityDate).toBeNull();
      expect(signals.relationships).toEqual([]);
    });
  });
});
