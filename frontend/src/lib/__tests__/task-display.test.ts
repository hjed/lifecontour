/**
 * Tests for the task display wording helpers.
 *
 * These are the strings the journal task surface shows for the two backend
 * enums it never displays raw. The lapse wording matters most: the
 * specification requires the journal listing to make clear that a task lapsed
 * because its due journal was *cancelled* rather than because time went by, so
 * the two must stay distinguishable from each other, not merely non-empty.
 */

import {
  lapseWording,
  statusActions,
  statusChangeWording,
  statusWording,
} from '@/lib/task-display';
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

describe('statusActions', () => {
  /** The action keys a status offers, in the order it offers them. */
  function keysFor(status: TaskStatus): string[] {
    return statusActions(status).map(action => action.key);
  }

  it('offers a not-done task completion and cancellation', () => {
    expect(keysFor(TaskStatus.NOT_DONE)).toEqual(['done', 'cancel']);
  });

  it('offers a done task the way back and cancellation', () => {
    expect(keysFor(TaskStatus.DONE)).toEqual(['not-done', 'cancel']);
  });

  /**
   * A cancelled task has exactly one exit and it is not a status call.
   *
   * The service refuses `cancelled → done` and `cancelled → not done` alike —
   * "cancelled is left only by retargeting" — so either button could do nothing
   * but draw a 409. Resurrection arrives with the retarget dialog.
   */
  it('offers a cancelled task no status action at all', () => {
    expect(statusActions(TaskStatus.CANCELLED)).toEqual([]);
  });

  /**
   * Guards the offer table against drifting from the service's transition
   * matrix. Written out here rather than imported so that changing the table
   * cannot silently change the thing that checks it.
   */
  it('never offers a transition the service refuses', () => {
    const refused = new Set([
      `${TaskStatus.CANCELLED}->${TaskStatus.DONE}`,
      `${TaskStatus.CANCELLED}->${TaskStatus.NOT_DONE}`,
    ]);

    const offered = Object.values(TaskStatus).flatMap(status =>
      statusActions(status).map(action => `${status}->${action.target}`)
    );

    expect(offered.filter(transition => refused.has(transition))).toEqual([]);
  });

  it('never offers the status the task already has', () => {
    Object.values(TaskStatus).forEach(status => {
      expect(statusActions(status).map(action => action.target)).not.toContain(
        status
      );
    });
  });

  /**
   * WCAG 2.5.3: a control's accessible name must contain its visible label, or
   * a user speaking what they can see cannot address it.
   */
  it('contains each visible label within its accessible name', () => {
    Object.values(TaskStatus).forEach(status => {
      statusActions(status).forEach(({ label, accessibleName }) => {
        expect(accessibleName.toLowerCase()).toContain(label.toLowerCase());
      });
    });
  });

  /**
   * Three distinct names across the whole table: completion, the way back, and
   * cancellation — the last shared by the two statuses that offer it, since it
   * is the same act either way.
   */
  it('names three acts across the whole table, no two alike', () => {
    const names = Object.values(TaskStatus).flatMap(status =>
      statusActions(status).map(action => action.accessibleName)
    );

    expect(new Set(names).size).toBe(3);
  });
});

describe('statusChangeWording', () => {
  it.each([
    [TaskStatus.DONE, /done/i],
    [TaskStatus.NOT_DONE, /not done/i],
    [TaskStatus.CANCELLED, /cancelled/i],
  ])('says what happened when a task becomes %s', (status, expected) => {
    expect(statusChangeWording(status)).toMatch(expected);
  });

  /**
   * Asserted pairwise rather than one regex per status: three tests each
   * checking "mentions done" would all survive the three being collapsed into
   * one string, which is the whole point of wording the result at all.
   */
  it('words all three outcomes differently', () => {
    const done = statusChangeWording(TaskStatus.DONE);
    const notDone = statusChangeWording(TaskStatus.NOT_DONE);
    const cancelled = statusChangeWording(TaskStatus.CANCELLED);

    expect(done).not.toBe(notDone);
    expect(done).not.toBe(cancelled);
    expect(notDone).not.toBe(cancelled);
  });

  it('never reports a status change as the generic update message', () => {
    Object.values(TaskStatus).forEach(status => {
      expect(statusChangeWording(status)).not.toBe('Task updated successfully');
    });
  });
});
