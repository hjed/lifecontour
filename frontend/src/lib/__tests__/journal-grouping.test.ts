import {
  groupJournalsByDay,
  JournalDayGroup,
  CollapsedEmptyGroup,
} from '../journal-grouping';
import { DisplayJournal } from '@/utils/journalTransformers';
import { format, addDays } from 'date-fns';

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

function assertIsDayGroup(group: unknown): asserts group is JournalDayGroup {
  expect((group as { type?: unknown }).type).toBe('day');
}

function assertIsCollapsedGroup(
  group: unknown
): asserts group is CollapsedEmptyGroup {
  expect((group as { type?: unknown }).type).toBe('collapsed-empty');
}

describe('journal-grouping', () => {
  const today = new Date();

  const getRelativeDateStr = (daysOffset: number = 0) =>
    format(addDays(today, daysOffset), 'yyyy-MM-dd');

  const getRelativeTimeStr = (
    daysOffset: number = 0,
    timeStr: string = '10:00:00'
  ) => `${getRelativeDateStr(daysOffset)}T${timeStr}`;

  describe('groupJournalsByDay', () => {
    it('creates contiguous day groups including empty days, ordered ascending', () => {
      const todayStr = getRelativeDateStr(0);
      const day2Str = getRelativeDateStr(1);
      const day3Str = getRelativeDateStr(2);

      const journals = [
        createMockJournal('1', getRelativeTimeStr(0, '10:00:00')),
        createMockJournal('2', getRelativeTimeStr(2, '15:00:00')),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: todayStr,
        endDate: day3Str,
        collapseEmpty: false,
      });

      expect(result).toHaveLength(3);

      assertIsDayGroup(result[0]);
      expect(result[0].date).toBe(todayStr);
      expect(result[0].isEmpty).toBe(false);
      expect(result[0].journals).toHaveLength(1);

      assertIsDayGroup(result[1]);
      expect(result[1].date).toBe(day2Str);
      expect(result[1].isEmpty).toBe(true);
      expect(result[1].journals).toHaveLength(0);

      assertIsDayGroup(result[2]);
      expect(result[2].date).toBe(day3Str);
      expect(result[2].isEmpty).toBe(false);
      expect(result[2].journals).toHaveLength(1);
    });

    it('collapses empty days when filter is applied', () => {
      const todayStr = getRelativeDateStr(0);
      const day3Str = getRelativeDateStr(2);

      const journals = [
        createMockJournal('1', getRelativeTimeStr(0, '10:00:00')),
        createMockJournal('2', getRelativeTimeStr(2, '15:00:00')),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: todayStr,
        endDate: day3Str,
        collapseEmpty: true,
      });

      expect(result).toHaveLength(2);

      assertIsDayGroup(result[0]);
      expect(result[0].date).toBe(todayStr);

      assertIsDayGroup(result[1]);
      expect(result[1].date).toBe(day3Str);
    });

    it('sorts journals within a day correctly by date ascending', () => {
      const todayStr = getRelativeDateStr(0);

      const journals = [
        createMockJournal('2', getRelativeTimeStr(0, '15:00:00')),
        createMockJournal('1', getRelativeTimeStr(0, '10:00:00')),
        createMockJournal('3', getRelativeTimeStr(0, '18:00:00')),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: todayStr,
        endDate: todayStr,
        collapseEmpty: false,
      });

      expect(result).toHaveLength(1);
      assertIsDayGroup(result[0]);
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
      assertIsDayGroup(result[0]);
      expect(result[0].date).toBe(dateStr);
    });

    it('returns empty array when bounds are inverted', () => {
      const result = groupJournalsByDay({
        journals: [],
        startDate: getRelativeDateStr(2),
        endDate: getRelativeDateStr(0),
        collapseEmpty: false,
      });
      expect(result).toHaveLength(0);
    });

    it('handles multiple journals in multiple days', () => {
      const todayStr = getRelativeDateStr(0);
      const day3Str = getRelativeDateStr(2);

      const journals = [
        createMockJournal('1', getRelativeTimeStr(0, '09:00:00')),
        createMockJournal('2', getRelativeTimeStr(0, '15:00:00')),
        createMockJournal('3', getRelativeTimeStr(2, '10:00:00')),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: todayStr,
        endDate: day3Str,
        collapseEmpty: false,
      });

      expect(result).toHaveLength(3);

      assertIsDayGroup(result[0]);
      expect(result[0].date).toBe(todayStr);
      expect(result[0].journals).toHaveLength(2);
      expect(result[0].journals[0].id).toBe('1');
      expect(result[0].journals[1].id).toBe('2');

      assertIsDayGroup(result[1]);
      expect(result[1].journals).toHaveLength(0);

      assertIsDayGroup(result[2]);
      expect(result[2].date).toBe(day3Str);
      expect(result[2].journals).toHaveLength(1);
      expect(result[2].journals[0].id).toBe('3');
    });

    it('collapses 7 or more consecutive empty days into a CollapsedEmptyGroup', () => {
      const todayStr = getRelativeDateStr(0);
      const day8Str = getRelativeDateStr(8);

      const journals = [
        createMockJournal('1', getRelativeTimeStr(0, '10:00:00')),
        createMockJournal('2', getRelativeTimeStr(8, '10:00:00')),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: todayStr,
        endDate: day8Str,
        collapseEmpty: false,
      });

      expect(result).toHaveLength(3);
      expect(result[0].type).toBe('day');
      expect(result[1].type).toBe('collapsed-empty');
      expect(result[2].type).toBe('day');

      assertIsCollapsedGroup(result[1]);
      expect(result[1].daysCount).toBe(7);
      expect(result[1].startDate).toBe(getRelativeDateStr(1));
      expect(result[1].endDate).toBe(getRelativeDateStr(7));
    });

    it('does not collapse fewer than 7 consecutive empty days', () => {
      const todayStr = getRelativeDateStr(0);
      const day7Str = getRelativeDateStr(7);

      const journals = [
        createMockJournal('1', getRelativeTimeStr(0, '10:00:00')),
        createMockJournal('2', getRelativeTimeStr(7, '10:00:00')),
      ];

      const result = groupJournalsByDay({
        journals,
        startDate: todayStr,
        endDate: day7Str,
        collapseEmpty: false,
      });

      expect(result).toHaveLength(8);
      result.forEach(group => {
        assertIsDayGroup(group);
      });
    });
  });
});
