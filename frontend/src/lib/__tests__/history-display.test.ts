/**
 * Tests for the task-aware wording of history entries.
 *
 * The wording lives in a pure function rather than inside `ActivityItem` for
 * the reason `lib/task-display.ts` exists: what a task's history entry *says*
 * is a product rule — the specification's *Where tasks appear* turns on the
 * contact entry being a record rather than an offer — and a pure function is
 * what lets a test assert it without rendering.
 *
 * Two things are load-bearing here. The function is gated on `entity_type`,
 * because the marker vocabulary is **shared**: a contact's own history writes
 * `field_name="status"` carrying `"created"`, and a journal writes
 * `__created__`, so wording by field name alone would relabel other domains'
 * rows. And the **same row** reads differently on the two feeds it can appear
 * in, because on a task's own history the interesting party is the contact and
 * on a contact's history it is the task.
 */

import { taskEntryDescription } from '../history-display';

const taskRow = (
  field_name: string,
  old_value: string | null,
  new_value: string | null
) => ({ entity_type: 'task', field_name, old_value, new_value });

const linkRow = (contactId: number) =>
  taskRow(`contact:${contactId}`, null, String(contactId));

const unlinkRow = (contactId: number) =>
  taskRow(`contact:${contactId}`, String(contactId), null);

describe('taskEntryDescription', () => {
  describe('a task lifecycle row on the task’s own feed', () => {
    it('opens the history with what the task was', () => {
      expect(
        taskEntryDescription(
          taskRow('__created__', null, 'Book the venue'),
          'task'
        )
      ).toBe('Task created: “Book the venue”');
    });

    it('words a create with no text without an empty quotation', () => {
      expect(
        taskEntryDescription(taskRow('__created__', null, null), 'task')
      ).toBe('Task created');
    });

    it('words the delete marker, which carries no values at all', () => {
      expect(
        taskEntryDescription(taskRow('__deleted__', null, null), 'task')
      ).toBe('Task deleted');
    });

    it('words a status move in the wording the rest of the app uses', () => {
      expect(
        taskEntryDescription(taskRow('status', 'not_done', 'done'), 'task')
      ).toBe('Status changed from Not done to Done');
    });

    it('words a retarget without showing the raw journal ids', () => {
      const description = taskEntryDescription(
        taskRow('due_journal_id', '3', '4'),
        'task'
      );

      expect(description).toBe('Due journal changed');
      expect(description).not.toContain('3');
      expect(description).not.toContain('4');
    });

    it('words the creating journal moving, which only a merge can do', () => {
      // The specification calls the creating journal set once and never
      // changed; a journal merge is its one exception, so this row exists and
      // has to read as something. Without the case it falls through to the
      // generic wording and a user is shown "Creating Journal Id".
      const description = taskEntryDescription(
        taskRow('creating_journal_id', '3', '4'),
        'task'
      );

      expect(description).toBe('Creating journal changed');
      expect(description).not.toContain('3');
      expect(description).not.toContain('4');
    });

    it('words an intermediate journal link and its removal', () => {
      expect(
        taskEntryDescription(taskRow('journal:7', null, '7'), 'task')
      ).toBe('Linked to a journal');
      expect(
        taskEntryDescription(taskRow('journal:7', '7', null), 'task')
      ).toBe('Unlinked from a journal');
    });

    it('words a status row whose values are missing or unrecognised', () => {
      // A status row always carries both sides today, and an unknown status
      // cannot be produced by this backend — but the wording is a string a user
      // reads, so neither case may render "undefined".
      expect(
        taskEntryDescription(taskRow('status', null, 'done'), 'task')
      ).toBe('Status changed from unknown to Done');
      expect(
        taskEntryDescription(taskRow('status', 'not_done', 'abandoned'), 'task')
      ).toBe('Status changed from Not done to abandoned');
    });

    it('leaves a reword to the generic wording, which already reads well', () => {
      expect(
        taskEntryDescription(taskRow('text', 'Old', 'New'), 'task')
      ).toBeNull();
    });

    it('leaves a field name it does not know to the generic wording', () => {
      expect(
        taskEntryDescription(taskRow('something_new', 'a', 'b'), 'task')
      ).toBeNull();
    });
  });

  describe('a contact-membership row, read from each end', () => {
    it('names the contact on the task’s own feed', () => {
      expect(taskEntryDescription(linkRow(12), 'task')).toBe(
        'Linked a contact'
      );
      expect(taskEntryDescription(unlinkRow(12), 'task')).toBe(
        'Unlinked a contact'
      );
    });

    it('names the task on the contact’s feed', () => {
      expect(taskEntryDescription(linkRow(12), 'contact')).toBe(
        'Linked to a task'
      );
      expect(taskEntryDescription(unlinkRow(12), 'contact')).toBe(
        'Unlinked from a task'
      );
    });

    it('says something different on each feed, not the same line twice', () => {
      // Asserted as a difference rather than as two independent strings: two
      // tests each checking "contains task" would both pass after the two
      // wordings were collapsed into one.
      expect(taskEntryDescription(linkRow(12), 'task')).not.toBe(
        taskEntryDescription(linkRow(12), 'contact')
      );
      expect(taskEntryDescription(unlinkRow(12), 'task')).not.toBe(
        taskEntryDescription(unlinkRow(12), 'contact')
      );
    });

    it('never shows the reader an id they cannot use', () => {
      // Both values on this row are the *contact's* id, which is meaningless
      // on their own page and no use on the task's.
      for (const surface of ['task', 'contact'] as const) {
        expect(taskEntryDescription(linkRow(12), surface)).not.toContain('12');
      }
    });
  });

  describe('rows belonging to another domain', () => {
    it('leaves a contact’s own create marker alone', () => {
      // Contacts record creation as `field_name="status"` carrying "created".
      // Wording by field name alone would call this a task status move.
      expect(
        taskEntryDescription(
          {
            entity_type: 'contact',
            field_name: 'status',
            old_value: null,
            new_value: 'created',
          },
          'contact'
        )
      ).toBeNull();
    });

    it('leaves a journal’s create marker alone', () => {
      expect(
        taskEntryDescription(
          {
            entity_type: 'journal',
            field_name: '__created__',
            old_value: null,
            new_value: 'My journal',
          },
          'journal'
        )
      ).toBeNull();
    });
  });
});

/**
 * Naming the task an entry is about.
 *
 * A contact-membership row carries the *contact's* id in both of its values, so
 * on the person's own page nothing in the row identifies the commitment. The
 * read supplies the name as `entity_label`; a task has no route of its own to
 * link to instead, so this is the only thing that makes the entry a record of
 * something.
 */
describe('taskEntryDescription — the task’s name', () => {
  const labelled = (
    field_name: string,
    new_value: string | null,
    entity_label: string | null
  ) => ({
    entity_type: 'task',
    field_name,
    old_value: null,
    new_value,
    entity_label,
  });

  it('names the task on a link entry', () => {
    expect(
      taskEntryDescription(
        labelled('contact:12', '12', 'Return the borrowed harness'),
        'contact'
      )
    ).toBe('Linked to a task: “Return the borrowed harness”');
  });

  it('names it on an unlink entry too', () => {
    expect(
      taskEntryDescription(
        {
          entity_type: 'task',
          field_name: 'contact:12',
          old_value: '12',
          new_value: null,
          entity_label: 'Return the borrowed harness',
        },
        'contact'
      )
    ).toBe('Unlinked from a task: “Return the borrowed harness”');
  });

  it('names it on the delete marker, which is where it matters most', () => {
    // A hard-deleted task cannot be looked up anywhere else.
    expect(
      taskEntryDescription(
        labelled('__deleted__', null, 'Return the borrowed harness'),
        'contact'
      )
    ).toBe('Task deleted: “Return the borrowed harness”');
  });

  it('falls back to the unnamed wording while projection catches up', () => {
    // Absent is not the same as "the task has no name"; a placeholder would
    // claim the second.
    expect(
      taskEntryDescription(labelled('contact:12', '12', null), 'contact')
    ).toBe('Linked to a task');
    expect(
      taskEntryDescription(
        {
          entity_type: 'task',
          field_name: 'contact:12',
          old_value: null,
          new_value: '12',
        },
        'contact'
      )
    ).toBe('Linked to a task');
  });

  it('does not name it on the task’s own feed', () => {
    // The reader is looking at the task; repeating its text on every line of
    // its own history is noise.
    expect(
      taskEntryDescription(
        labelled('contact:12', '12', 'Return the borrowed harness'),
        'task'
      )
    ).toBe('Linked a contact');
  });
});
