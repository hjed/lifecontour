/**
 * The tasks section's wording and colour rules (**W22**, **W25**).
 *
 * Pure functions, asserted without rendering anything. Two product rules live
 * here rather than in the row: the chip is **relative first and absolute
 * after**, and the accent colour is keyed to the *due journal* rather than to
 * how soon the task falls due — which is the one thing **W25** rules out in
 * terms.
 */

import {
  CHART_ACCENTS,
  CHART_CHIPS,
  dueAccentClassName,
  dueChipClassName,
  dueChipLabel,
  showAllDueLabel,
  taskTextId,
} from '@/lib/dashboard-tasks-display';
import type { HomeDashboardTask } from '@/lib/api/home-dashboard';
import { readFileSync } from 'fs';
import { join } from 'path';

/** A row as the payload sends one, with only the two fields a chip reads. */
function task(daysAway: number, dueDate: string): HomeDashboardTask {
  return {
    task_id: 1,
    text: 'Send the deposit',
    due_journal: { id: 7, title: 'Friday', date: dueDate },
    days_away: daysAway,
    contacts: [],
  };
}

describe('dueChipLabel', () => {
  it('reads Today on the window’s first day', () => {
    expect(dueChipLabel(task(0, '2026-07-29'))).toBe('Today');
  });

  it('reads Tomorrow on the day after it', () => {
    expect(dueChipLabel(task(1, '2026-07-30'))).toBe('Tomorrow');
  });

  it.each([
    [2, '2026-08-01', 'Sat 1 Aug'],
    [7, '2026-08-05', 'Wed 5 Aug'],
  ])(
    'falls back to a short absolute form at %i days away',
    (daysAway, dueDate, expected) => {
      expect(dueChipLabel(task(daysAway, dueDate))).toBe(expected);
    }
  );

  /**
   * The relative half is decided by `days_away` and the absolute half is read
   * off `due_journal.date`, and **neither is worked out here**.
   *
   * `days_away` counts from the window's first day, which the server resolved
   * in the user's configured zone, and `due_journal.date` is a calendar day it
   * resolved in the same zone. A chip that subtracted one from the browser's
   * today would be right most of the time and wrong in the hours that matter —
   * pinned against a real browser clock in
   * `DashboardTaskRow.timezone.test.tsx`. What this test can pin is that the
   * two inputs are used *independently*: a payload whose date disagrees with
   * its offset still labels itself from the offset.
   */
  it('trusts days_away over the due date, and consults no clock', () => {
    // A date three months off, sent with days_away 0. Anything deriving the
    // label from the date would say "Fri 30 Oct".
    expect(dueChipLabel(task(0, '2026-10-30'))).toBe('Today');
  });
});

describe('dueAccentClassName', () => {
  /**
   * **W25**: the chip's colour tracks the row's accent bar, *i.e.* the due
   * journal — explicitly **not** a proximity scale. The payload carries no
   * colour for a journal, so the colour is derived from the one stable thing
   * the row knows about it: its id.
   */
  it('gives two tasks due in the same journal the same colour', () => {
    expect(dueAccentClassName(42)).toBe(dueAccentClassName(42));
  });

  it('gives tasks due in different journals different colours', () => {
    expect(dueAccentClassName(1)).not.toBe(dueAccentClassName(2));
  });

  it('answers with one of the five chart accents and nothing else', () => {
    for (const id of [0, 1, 2, 3, 4, 5, 6, 97, 1_000_003]) {
      expect(CHART_ACCENTS).toContain(dueAccentClassName(id));
    }
  });

  /**
   * The classes are **literal strings in a tuple**, never composed.
   *
   * Tailwind only emits utilities it can find in the source, so a
   * `bg-chart-${n}` built at runtime produces no CSS at all and the bar draws
   * as nothing. Asserting the literals here is what makes that failure a red
   * test rather than an invisible accent bar.
   */
  it('is built from literal class names Tailwind can see', () => {
    expect([...CHART_ACCENTS]).toEqual([
      'bg-chart-1',
      'bg-chart-2',
      'bg-chart-3',
      'bg-chart-4',
      'bg-chart-5',
    ]);
  });

  it('uses every accent rather than crowding onto a few', () => {
    const used = new Set([1, 2, 3, 4, 5].map(dueAccentClassName));
    expect(used.size).toBe(CHART_ACCENTS.length);
  });

  it('survives an id larger than the palette', () => {
    expect(dueAccentClassName(6)).toBe(dueAccentClassName(1));
  });
});

describe('dueChipClassName', () => {
  /**
   * **W22** draws the accent as a solid bar and **W25** draws the chip
   * bordered, so the two need different utilities — but the *same* colour, and
   * that agreement is the whole of what W25 asks. Asserted by index rather
   * than by comparing strings that were never going to be equal.
   */
  it('takes the same colour as the row’s accent bar', () => {
    for (const id of [1, 2, 3, 4, 5, 97]) {
      expect(CHART_CHIPS.indexOf(dueChipClassName(id))).toBe(
        CHART_ACCENTS.indexOf(dueAccentClassName(id))
      );
    }
  });

  it('is built from literal class names Tailwind can see', () => {
    expect([...CHART_CHIPS]).toEqual([
      'border-chart-1 text-chart-1',
      'border-chart-2 text-chart-2',
      'border-chart-3 text-chart-3',
      'border-chart-4 text-chart-4',
      'border-chart-5 text-chart-5',
    ]);
  });
});

/**
 * The one claim in this module a *behavioural* test cannot make.
 *
 * Tailwind emits only the utilities it can find in the source, so a class name
 * assembled at runtime — `` `bg-chart-${n}` `` — produces no CSS and the accent
 * bar draws as nothing at all. That failure is invisible to every assertion
 * above, because the composed string is byte-identical to the literal one: a
 * mutation replacing the tuple lookup with a template literal passes the whole
 * suite. Proved by running exactly that mutation, which is why this test
 * exists.
 *
 * So the source is read instead, the way `tasks.test.ts` asserts that the API
 * client never calls `invalidateQueries` directly. A build-shaped invariant
 * needs a build-shaped assertion.
 */
describe('the classes Tailwind has to be able to see', () => {
  // Comments stripped first, because the module's own docstring names the
  // forbidden form in order to warn against it — and a guard that fired on the
  // explanation would be unfixable without deleting the explanation.
  const source = readFileSync(
    join(__dirname, '..', 'dashboard-tasks-display.ts'),
    'utf8'
  )
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');

  it('never assembles a chart class name at runtime', () => {
    expect(source).not.toMatch(/`[^`]*(?:bg|border|text)-chart-\$\{/);
  });

  it('still sees the form it is guarding against', () => {
    // The guard's own guard: a regex that matched nothing would pass this
    // suite for ever, so it is shown catching the shape it exists to catch.
    expect('return `bg-chart-${index}`;').toMatch(
      /`[^`]*(?:bg|border|text)-chart-\$\{/
    );
  });
});

describe('taskTextId', () => {
  /**
   * The row draws the text and the card mounts the actions that are
   * *described by* it, so both have to arrive at the same id without one
   * handing it to the other. Composed from the task id rather than `useId`
   * for exactly that reason.
   */
  it('is derivable from the task id alone, and unique per task', () => {
    expect(taskTextId(7)).toBe(taskTextId(7));
    expect(taskTextId(7)).not.toBe(taskTextId(8));
  });
});

describe('showAllDueLabel', () => {
  /**
   * **W28** writes the button out in full — *"Show all 7 due this week"* —
   * and it is a different sentence from the upcoming-dates section's
   * *"Show all 5 this week"* (**W32**). Two sections, two wordings, asserted
   * separately so neither can be quietly rewritten into the other's.
   *
   * The count names the **whole window** rather than the number hidden behind
   * the cap: the useful question is how much there is, not how much is
   * missing.
   */
  it('names the whole window in W28’s own words', () => {
    expect(showAllDueLabel(7)).toBe('Show all 7 due this week');
  });
});
