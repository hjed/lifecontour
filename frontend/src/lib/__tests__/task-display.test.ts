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
  canRetarget,
  deleteTaskDescription,
  lapseWording,
  linkRemovable,
  overdueWording,
  retargetAction,
  statusActions,
  statusChangeWording,
  statusWording,
  tasksDueWording,
} from '@/lib/task-display';
import { LapseReason, TaskLinkRole, TaskStatus } from '@/types/tasks';

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

describe('statusActions for a journal-only task', () => {
  const JOURNAL_ONLY = { onList: false };

  /** The action keys a status offers, in the order it offers them. */
  function keysFor(status: TaskStatus): string[] {
    return statusActions(status, JOURNAL_ONLY).map(action => action.key);
  }

  it('offers a not-done task completion and cancellation', () => {
    expect(keysFor(TaskStatus.NOT_DONE)).toEqual(['done', 'cancel']);
  });

  it('offers a done task the way back and cancellation', () => {
    expect(keysFor(TaskStatus.DONE)).toEqual(['not-done', 'cancel']);
  });

  /**
   * A cancelled journal-only task has exactly one exit and it is not a status
   * call.
   *
   * The service refuses `cancelled → done` and `cancelled → not done` alike for
   * it — "cancelled is left only by retargeting" — so either button could do
   * nothing but draw a 409. Resurrection arrives with the retarget dialog. (A
   * list task is reopened by its status — see the list-aware cases below.)
   */
  it('offers a cancelled task no status action at all', () => {
    expect(statusActions(TaskStatus.CANCELLED, JOURNAL_ONLY)).toEqual([]);
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
      statusActions(status, JOURNAL_ONLY).map(
        action => `${status}->${action.target}`
      )
    );

    expect(offered.filter(transition => refused.has(transition))).toEqual([]);
  });

  it('never offers the status the task already has', () => {
    Object.values(TaskStatus).forEach(status => {
      expect(
        statusActions(status, JOURNAL_ONLY).map(action => action.target)
      ).not.toContain(status);
    });
  });

  /**
   * WCAG 2.5.3: a control's accessible name must contain its visible label, or
   * a user speaking what they can see cannot address it.
   */
  it('contains each visible label within its accessible name', () => {
    Object.values(TaskStatus).forEach(status => {
      statusActions(status, JOURNAL_ONLY).forEach(
        ({ label, accessibleName }) => {
          expect(accessibleName.toLowerCase()).toContain(label.toLowerCase());
        }
      );
    });
  });

  /**
   * Three distinct names across the whole table: completion, the way back, and
   * cancellation — the last shared by the two statuses that offer it, since it
   * is the same act either way.
   */
  it('names three acts across the whole table, no two alike', () => {
    const names = Object.values(TaskStatus).flatMap(status =>
      statusActions(status, JOURNAL_ONLY).map(action => action.accessibleName)
    );

    expect(new Set(names).size).toBe(3);
  });
});

/**
 * A task on a list is never refused a status change: the service allows every
 * move between the three statuses on a list, so a done or cancelled list task
 * is reopened by its status rather than by a new due journal.
 */
describe('statusActions for a task on a list', () => {
  const ON_LIST = { onList: true };

  function keysFor(status: TaskStatus): string[] {
    return statusActions(status, ON_LIST).map(action => action.key);
  }

  it('offers a not-done list task completion and cancellation', () => {
    expect(keysFor(TaskStatus.NOT_DONE)).toEqual(['done', 'cancel']);
  });

  it('offers a done list task the way back and cancellation', () => {
    expect(keysFor(TaskStatus.DONE)).toEqual(['not-done', 'cancel']);
  });

  it('offers a cancelled list task the way back and completion', () => {
    expect(keysFor(TaskStatus.CANCELLED)).toEqual(['not-done', 'done']);
  });

  /**
   * Every move between two different statuses, written out rather than derived
   * so the table cannot drift from the service rule it mirrors.
   */
  it('offers every transition the service allows on a list, and no other', () => {
    const offered = Object.values(TaskStatus)
      .flatMap(status =>
        statusActions(status, ON_LIST).map(
          action => `${status}->${action.target}`
        )
      )
      .sort();

    expect(offered).toEqual(
      [
        `${TaskStatus.NOT_DONE}->${TaskStatus.DONE}`,
        `${TaskStatus.NOT_DONE}->${TaskStatus.CANCELLED}`,
        `${TaskStatus.DONE}->${TaskStatus.NOT_DONE}`,
        `${TaskStatus.DONE}->${TaskStatus.CANCELLED}`,
        `${TaskStatus.CANCELLED}->${TaskStatus.NOT_DONE}`,
        `${TaskStatus.CANCELLED}->${TaskStatus.DONE}`,
      ].sort()
    );
  });

  it('contains each visible label within its accessible name', () => {
    Object.values(TaskStatus).forEach(status => {
      statusActions(status, ON_LIST).forEach(({ label, accessibleName }) => {
        expect(accessibleName.toLowerCase()).toContain(label.toLowerCase());
      });
    });
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

/**
 * A list task's due journal is a plain date: changing it keeps the status, so
 * it is one offer whatever the status, and never worded as a reopen or a
 * resurrection — a list task neither lapses nor reopens on a date change.
 */
describe('retargetAction for a task on a list', () => {
  it.each(Object.values(TaskStatus))(
    'offers the same keeps-status reschedule for a %s task',
    status => {
      const offer = retargetAction(status, false, true);

      expect(offer.label).toBe('Reschedule');
      expect(offer.dialogDescription).toMatch(/keeps its status/i);
      expect(offer.dialogDescription).not.toMatch(/reopen/i);
      expect(offer.accessibleName.toLowerCase()).toContain('reschedule');
    }
  );

  it('ignores the lapse flag, which a list task never carries', () => {
    expect(retargetAction(TaskStatus.NOT_DONE, true, true)).toBe(
      retargetAction(TaskStatus.NOT_DONE, false, true)
    );
  });

  it('is worded differently from the journal-only reschedule', () => {
    expect(retargetAction(TaskStatus.NOT_DONE, false, true)).not.toBe(
      retargetAction(TaskStatus.NOT_DONE, false)
    );
  });
});

/**
 * Which tasks a journal page offers the dialog to. A journal-only task needs
 * both anchors, as it always has. A task on a list needs only a due journal to
 * move from: one with none is set from its details panel, not from a journal
 * page where it is only mentioned.
 */
describe('canRetarget', () => {
  it.each([
    [1, 2, true],
    [null, 2, false],
    [1, null, false],
    [null, null, false],
  ])(
    'a journal-only task with creating journal %p and due journal %p → %p',
    (creating_journal_id, due_journal_id, expected) => {
      expect(
        canRetarget({ creating_journal_id, due_journal_id, task_list_id: null })
      ).toBe(expected);
    }
  );

  it.each([
    [1, 2, true],
    [null, 2, true],
    [1, null, false],
    [null, null, false],
  ])(
    'a list task with creating journal %p and due journal %p → %p',
    (creating_journal_id, due_journal_id, expected) => {
      expect(
        canRetarget({ creating_journal_id, due_journal_id, task_list_id: 9 })
      ).toBe(expected);
    }
  );
});

describe('overdueWording', () => {
  const dueJournal = {
    id: 3,
    title: 'Offsite',
    date: '2026-11-13',
    cancelled: false,
  };

  it('names the due date when the task has one', () => {
    expect(
      overdueWording({ due_date: '2026-11-10', due_journal: null }).label
    ).toBe('Overdue · 10 Nov');
  });

  it("names the due journal's date when the task is due in a journal", () => {
    expect(
      overdueWording({ due_date: null, due_journal: dueJournal }).label
    ).toBe('Overdue · 13 Nov');
  });

  it('reads plain "Overdue" when there is no date to name', () => {
    expect(overdueWording({ due_date: null, due_journal: null }).label).toBe(
      'Overdue'
    );
  });

  it('explains that the date passed and the task is still not done', () => {
    const { description } = overdueWording({
      due_date: '2026-11-10',
      due_journal: null,
    });

    expect(description).toMatch(/overdue/i);
    expect(description).toMatch(/passed/i);
    expect(description).toMatch(/not done/i);
  });

  /**
   * The specification keeps the two markers apart: a list task is overdue and
   * never lapsed, so the words must not be confusable.
   */
  it('never words overdue as lapsed', () => {
    const { label, description } = overdueWording({
      due_date: null,
      due_journal: dueJournal,
    });

    expect(label).not.toMatch(/lapsed/i);
    expect(description).not.toMatch(/lapsed/i);
  });
});

describe('deleteTaskDescription', () => {
  it('tells a journal-only task that a new due journal reopens it', () => {
    const text = deleteTaskDescription({ onList: false });

    expect(text).toMatch(/permanent/i);
    expect(text).toMatch(/new due journal/i);
  });

  /**
   * A cancelled list task is reopened by its status, and the service refuses a
   * new due journal for it, so the journal-only advice would be false here.
   */
  it('tells a list task it stays on its list and can be set back to not done', () => {
    const text = deleteTaskDescription({ onList: true });

    expect(text).toMatch(/permanent/i);
    expect(text).toMatch(/stays on its list/i);
    expect(text).toMatch(/not done/i);
    expect(text).not.toMatch(/new due journal/i);
  });
});

/**
 * The rule behind criterion 2: "a mention link can be removed from the journal
 * that carries it; creating and due links offer no remove affordance".
 *
 * Asserted exhaustively over the role enum rather than one role at a time. A
 * test that only checked `mentioned` would still pass after an anchor role was
 * made removable, and the anchors are the half of this rule that matters — the
 * service reaches them only through `create_task` and `retarget_due_journal`,
 * and a remove button on one could do nothing but draw a 409.
 */
describe('linkRemovable', () => {
  it('allows a mention to be removed', () => {
    expect(linkRemovable(TaskLinkRole.MENTIONED)).toBe(true);
  });

  it.each([TaskLinkRole.DUE, TaskLinkRole.CREATED])(
    'refuses to remove the %s anchor',
    role => {
      expect(linkRemovable(role)).toBe(false);
    }
  );

  it('permits exactly one of the roles the listing groups by', () => {
    const removable = Object.values(TaskLinkRole).filter(linkRemovable);

    expect(removable).toEqual([TaskLinkRole.MENTIONED]);
  });
});

describe('tasksDueWording', () => {
  it('is singular for one commitment', () => {
    expect(tasksDueWording(1)).toBe('1 task due in this journal');
  });

  it('is plural for more than one', () => {
    expect(tasksDueWording(2)).toBe('2 tasks due in this journal');
    expect(tasksDueWording(11)).toBe('11 tasks due in this journal');
  });

  it('names the journal, because the badge sits on a row among many', () => {
    // The visible badge reads "2 due", which is unambiguous beside its journal
    // and meaningless read out of a list of thirty. The accessible name is the
    // one a screen-reader user hears on its own, so it has to carry the subject
    // the sighted layout supplies.
    expect(tasksDueWording(2)).toContain('in this journal');
  });
});
