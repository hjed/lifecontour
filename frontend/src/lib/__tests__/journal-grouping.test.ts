import { groupJournalsByDay } from '../journal-grouping';
import { DisplayJournal } from '@/utils/journalTransformers';

const createMockJournal = (id: string, startDate: string): DisplayJournal => ({
  id,
  title: `Journal ${id}`,
  content: 'Content',
  event_date_range: {
    start: startDate,
    end: startDate,
  },
  types: [],
  tags: [],
  contacts: [],
});

describe('journal-grouping', () => {
  describe('groupJournalsByDay', () => {
    it('creates contiguous day groups including empty days, ordered descending', () => {
      const journals = [
        createMockJournal('1', '2026-04-01T10:00:00'),
        createMockJournal('2', '2026-04-03T15:00:00'),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: '2026-04-01',
        endDate: '2026-04-03',
        collapseEmpty: false,
      });

      expect(result).toHaveLength(3);

      // Oldest (04-01) should be first
      expect(result[0].date).toBe('2026-04-01');
      expect(result[0].isEmpty).toBe(false);
      expect(result[0].journals).toHaveLength(1);

      expect(result[1].date).toBe('2026-04-02');
      expect(result[1].isEmpty).toBe(true);
      expect(result[1].journals).toHaveLength(0);

      expect(result[2].date).toBe('2026-04-03');
      expect(result[2].isEmpty).toBe(false);
      expect(result[2].journals).toHaveLength(1);
    });

    it('collapses empty days when filter is applied', () => {
      const journals = [
        createMockJournal('1', '2026-04-01T10:00:00'),
        createMockJournal('2', '2026-04-03T15:00:00'),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: '2026-04-01',
        endDate: '2026-04-03',
        collapseEmpty: true,
      });

      expect(result).toHaveLength(2);
      expect(result[0].date).toBe('2026-04-01'); // Ascending order
      expect(result[1].date).toBe('2026-04-03');
    });

    it('sorts journals within a day correctly by date ascending', () => {
      const journals = [
        createMockJournal('2', '2026-04-01T15:00:00'),
        createMockJournal('1', '2026-04-01T10:00:00'),
        createMockJournal('3', '2026-04-01T18:00:00'),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: '2026-04-01',
        endDate: '2026-04-01',
        collapseEmpty: false,
      });

      expect(result).toHaveLength(1);
      // Within the day, chronological (ascending) order
      expect(result[0].journals[0].id).toBe('1');
      expect(result[0].journals[1].id).toBe('2');
      expect(result[0].journals[2].id).toBe('3');
    });

    it('groups journals purely based on local date part, not timezone shifts', () => {
      const d = new Date();
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const dateStr = `${year}-${month}-${day}`;

      const journals = [createMockJournal('1', d.toISOString())];

      const result = groupJournalsByDay({
        journals,
        startDate: dateStr,
        endDate: dateStr,
        collapseEmpty: false,
      });

      expect(result).toHaveLength(1);
      expect(result[0].date).toBe(dateStr);
    });

    it('returns empty array when bounds are inverted', () => {
      const result = groupJournalsByDay({
        journals: [],
        startDate: '2026-04-03',
        endDate: '2026-04-01',
        collapseEmpty: false,
      });
      expect(result).toHaveLength(0);
    });

    it('handles multiple journals in multiple days', () => {
      const journals = [
        createMockJournal('1', '2026-04-01T09:00:00'),
        createMockJournal('2', '2026-04-01T15:00:00'),
        createMockJournal('3', '2026-04-03T10:00:00'),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: '2026-04-01',
        endDate: '2026-04-03',
        collapseEmpty: false,
      });
      expect(result).toHaveLength(3);
      // Ascending order: 04-01 is first
      expect(result[0].journals).toHaveLength(2); // 04-01
      expect(result[1].journals).toHaveLength(0);
      expect(result[2].journals).toHaveLength(1);
      expect(result[2].journals[0].id).toBe('3');
    });
  });
});
