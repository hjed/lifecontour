/**
 * Tests for the journal resource → display transform.
 *
 * The transform is a whitelist: every field the list rows render has to be
 * named in it, and one that is not simply vanishes between the wire and the
 * component with nothing to show for it. So the fields added by a phase are
 * asserted here rather than only through whatever renders them — a component
 * test builds its `DisplayJournal` directly and would pass over a transform
 * that had dropped the field on the way.
 */

import { JournalResource, JournalType } from '@/types/journals';
import { transformJournalForDisplay } from '@/utils/journalTransformers';

const baseJournal: JournalResource = {
  type: 'journals',
  id: '1',
  attributes: {
    title: 'Permit Meeting',
    content: 'content',
    event_date_range: { start: '2026-08-09', end: '2026-08-09' },
    types: [JournalType.NOTE],
    tags: [],
    contacts: [],
  },
};

describe('transformJournalForDisplay', () => {
  it('carries the tasks-due count through to the row', () => {
    const display = transformJournalForDisplay({
      ...baseJournal,
      attributes: { ...baseJournal.attributes, tasks_due_count: 2 },
    });

    expect(display.tasks_due_count).toBe(2);
  });

  it('leaves the count undefined when the payload omits it', () => {
    // Not coerced to zero. "The server did not say" and "the server said none"
    // are different facts, and the row draws a different conclusion from each:
    // an older or partial payload should render no indicator rather than assert
    // that a journal has nothing due in it.
    const display = transformJournalForDisplay(baseJournal);

    expect(display.tasks_due_count).toBeUndefined();
  });

  it('leaves an explicit null as null', () => {
    // What the endpoints that do not compute the count actually send. It must
    // survive the transform as null rather than becoming zero, because zero is
    // a claim about the journal and null is the absence of one.
    const display = transformJournalForDisplay({
      ...baseJournal,
      attributes: { ...baseJournal.attributes, tasks_due_count: null },
    });

    expect(display.tasks_due_count).toBeNull();
  });

  it('carries a zero as a zero', () => {
    const display = transformJournalForDisplay({
      ...baseJournal,
      attributes: { ...baseJournal.attributes, tasks_due_count: 0 },
    });

    expect(display.tasks_due_count).toBe(0);
  });
});
