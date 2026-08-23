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
  retargetAction,
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

describe('retargetAction', () => {
  /**
   * The four cases the wording has to tell apart. A retarget is one call to
   * one endpoint, but it is four different things to ask for: bringing a
   * lapsed commitment back, bringing a cancelled one back, moving a live one,
   * and reopening one that was finished.
   */
  const LAPSED = retargetAction(TaskStatus.NOT_DONE, true);
  const CANCELLED = retargetAction(TaskStatus.CANCELLED, false);
  const LIVE = retargetAction(TaskStatus.NOT_DONE, false);
  const DONE = retargetAction(TaskStatus.DONE, false);

  it('offers a lapsed task resurrection', () => {
    expect(LAPSED.label).toBe('Resurrect');
  });

  it('offers a cancelled task resurrection — its one exit', () => {
    expect(CANCELLED.label).toBe('Resurrect');
  });

  it('offers a live task a reschedule rather than a resurrection', () => {
    expect(LIVE.label).toBe('Reschedule');
  });

  it('offers a done task a reopen, naming what retargeting will do to it', () => {
    expect(DONE.label).toBe('Reopen');
  });

  /**
   * A cancelled task is never reported lapsed by the read model — a commitment
   * called off cannot then be let slide — but the offer must not depend on
   * that being true, since the caller passes both values through.
   */
  it('offers resurrection for a cancelled task whatever the lapse flag says', () => {
    expect(retargetAction(TaskStatus.CANCELLED, true).label).toBe('Resurrect');
  });

  it('is one action under one key, whatever it is called', () => {
    [LAPSED, CANCELLED, LIVE, DONE].forEach(offer => {
      expect(offer.key).toBe('retarget');
    });
  });

  /**
   * WCAG 2.5.3, as `statusActions` already guards: a control's accessible name
   * must contain its visible label.
   */
  it('contains each visible label within its accessible name', () => {
    [LAPSED, CANCELLED, LIVE, DONE].forEach(({ label, accessibleName }) => {
      expect(accessibleName.toLowerCase()).toContain(label.toLowerCase());
    });
  });

  it('words three distinct acts, resurrection shared by the two that need it', () => {
    const labels = [LAPSED, CANCELLED, LIVE, DONE].map(offer => offer.label);

    expect(new Set(labels).size).toBe(3);
  });

  /**
   * The dialog is the surface the specification's "the UI must say so before
   * it happens" lands on, so the done case's own text has to carry the reopen
   * rather than leaving it to the confirmation step alone.
   */
  it('warns a done task that retargeting reopens it as not done', () => {
    expect(DONE.dialogDescription).toMatch(/not done/i);
    expect(DONE.dialogDescription).toMatch(/reopen/i);
  });

  it('tells a cancelled task that a new future journal is the way back', () => {
    expect(CANCELLED.dialogDescription).toMatch(/future/i);
    expect(CANCELLED.dialogDescription).toMatch(/journal/i);
  });

  it('distinguishes a lapsed task from a live one in the dialog, not only in the button', () => {
    expect(LAPSED.dialogTitle).not.toBe(LIVE.dialogTitle);
    expect(LAPSED.dialogDescription).not.toBe(LIVE.dialogDescription);
  });

  it('gives every case a non-empty title, description and submit label', () => {
    [LAPSED, CANCELLED, LIVE, DONE].forEach(offer => {
      expect(offer.dialogTitle.length).toBeGreaterThan(0);
      expect(offer.dialogDescription.length).toBeGreaterThan(0);
      expect(offer.submitLabel.length).toBeGreaterThan(0);
    });
  });
});
