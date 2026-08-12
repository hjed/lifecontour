/**
 * Tests for the task display wording helpers.
 *
 * These are the strings the journal task surface shows for the two backend
 * enums it never displays raw. The lapse wording matters most: the
 * specification requires the journal listing to make clear that a task lapsed
 * because its due journal was *cancelled* rather than because time went by, so
 * the two must stay distinguishable from each other, not merely non-empty.
 */

import { lapseWording, statusWording } from '@/lib/task-display';
import { LapseReason, TaskStatus } from '@/types/tasks';

describe('statusWording', () => {
  it.each([
    [TaskStatus.NOT_DONE, 'Not done'],
    [TaskStatus.DONE, 'Done'],
    [TaskStatus.CANCELLED, 'Cancelled'],
  ])('words %s as "%s"', (status, expected) => {
    expect(statusWording(status)).toBe(expected);
  });

  it('gives every status its own wording', () => {
    const words = [
      statusWording(TaskStatus.NOT_DONE),
      statusWording(TaskStatus.DONE),
      statusWording(TaskStatus.CANCELLED),
    ];

    expect(new Set(words).size).toBe(words.length);
  });
});

describe('lapseWording', () => {
  it('names a passed date as the reason', () => {
    const { label, description } = lapseWording(LapseReason.DATE_PASSED);

    expect(label).toMatch(/lapsed/i);
    expect(label).toMatch(/date/i);
    expect(description).toMatch(/passed/i);
  });

  it('names a cancelled due journal as the reason', () => {
    const { label, description } = lapseWording(
      LapseReason.DUE_JOURNAL_CANCELLED
    );

    expect(label).toMatch(/lapsed/i);
    expect(label).toMatch(/cancelled/i);
    expect(description).toMatch(/cancelled/i);
  });

  it('words the two reasons differently, label and description alike', () => {
    const passed = lapseWording(LapseReason.DATE_PASSED);
    const cancelled = lapseWording(LapseReason.DUE_JOURNAL_CANCELLED);

    expect(passed.label).not.toBe(cancelled.label);
    expect(passed.description).not.toBe(cancelled.description);
  });

  it.each([[null], [undefined]])(
    'falls back to a bare marker when the reason is %p',
    reason => {
      const { label, description } = lapseWording(reason);

      expect(label).toBe('Lapsed');
      expect(description).toMatch(/lapsed/i);
    }
  );

  it('never words the fallback as either specific reason', () => {
    const fallback = lapseWording(null);

    expect(fallback.label).not.toBe(
      lapseWording(LapseReason.DATE_PASSED).label
    );
    expect(fallback.label).not.toBe(
      lapseWording(LapseReason.DUE_JOURNAL_CANCELLED).label
    );
  });
});
