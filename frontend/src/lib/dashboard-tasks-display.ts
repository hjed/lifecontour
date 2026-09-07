/**
 * The tasks section's wording and colour rules (**W22**, **W25**).
 *
 * A module rather than the component, beside `upcoming-dates-display` and
 * `agenda-display`: both of these are product rules rather than formatting —
 * one decides when a date stops being spoken of relatively, the other decides
 * what a row's colour *means* — and a pure function can be asserted without a
 * DOM.
 *
 * Neither consults a clock, and that is load-bearing rather than tidy. Both
 * values they read were resolved by the server in the user's configured
 * timezone; deriving either from the browser's would answer a day out near
 * midnight in any other zone.
 */

import type { HomeDashboardTask } from '@/lib/api/home-dashboard';
import { formatIsoShortWeekdayDate } from '@/lib/date-utils';

/**
 * The palette a row's accent bar and due chip are drawn from.
 *
 * **Literal class names in a tuple, never composed.** Tailwind emits only the
 * utilities it can find in the source, so a `bg-chart-${n}` assembled at
 * runtime produces no CSS at all and the accent draws as nothing at all — a
 * failure that is invisible in review and in every test that does not assert
 * the string. The five are the theme's chart colours, defined for light and
 * dark alike in `globals.css`.
 */
export const CHART_ACCENTS = [
  'bg-chart-1',
  'bg-chart-2',
  'bg-chart-3',
  'bg-chart-4',
  'bg-chart-5',
] as const;

/** One of the five accents, so a composed class name cannot be returned. */
export type ChartAccentClass = (typeof CHART_ACCENTS)[number];

/**
 * The same five colours as a **bordered** chip rather than a filled bar.
 *
 * **W25** draws the chip bordered and colour-coded where **W22** draws the
 * accent as a solid bar, so the two need different utilities from one colour.
 * Written out for the same reason {@link CHART_ACCENTS} is: Tailwind cannot
 * see a class it did not find in the source.
 */
export const CHART_CHIPS = [
  'border-chart-1 text-chart-1',
  'border-chart-2 text-chart-2',
  'border-chart-3 text-chart-3',
  'border-chart-4 text-chart-4',
  'border-chart-5 text-chart-5',
] as const;

/** One of the five chip colourings, for the reason `ChartAccentClass` exists. */
export type ChartChipClass = (typeof CHART_CHIPS)[number];

/**
 * Which of the five colours a due journal takes.
 *
 * **W25** says the chip's colour tracks the accent bar, *i.e.* the due
 * journal, and says in terms that it is **not** a proximity scale — in the
 * wireframe's own sample, `Tomorrow` and `Wed 5 Aug` share a colour while the
 * nearer `Sat 1 Aug` differs. The payload carries no colour for a journal
 * (`due_journal` is id, title and date), so the colour is derived from the one
 * stable thing the row knows about it.
 *
 * Keyed to the id means two tasks due in the same journal read as a pair,
 * which is the grouping the wireframe draws, and it is stable across renders
 * and reloads without the payload having to carry anything new. It is
 * arbitrary *which* colour a journal gets — that is what "sample noise rather
 * than a rule" allows — but not arbitrary that the same journal keeps it.
 *
 * `Math.abs` because an id is only ever positive in practice and `%` on a
 * negative would index off the front of the tuple if that ever stopped being
 * true.
 */
function accentIndex(journalId: number): number {
  return Math.abs(journalId) % CHART_ACCENTS.length;
}

/** The solid accent bar down a row's left edge (**W22**). */
export function dueAccentClassName(journalId: number): ChartAccentClass {
  return CHART_ACCENTS[accentIndex(journalId)] as ChartAccentClass;
}

/**
 * The due chip's border and text colour (**W25**).
 *
 * Derived from the same index as {@link dueAccentClassName}, so the chip and
 * the bar cannot drift apart — which is the whole of what W25 asks of the
 * colour.
 */
export function dueChipClassName(journalId: number): ChartChipClass {
  return CHART_CHIPS[accentIndex(journalId)] as ChartChipClass;
}

/**
 * The id of the element carrying a task's text.
 *
 * The row's action group is *described by* the commitment it acts on rather
 * than each button being given a label long enough to identify it — the
 * arrangement `JournalTaskActions` established, since every row's button is
 * named the same thing. The card mounts the actions and the row draws the
 * text, so the id has to be derivable by both; composed from the task id
 * rather than `useId` for that reason, and unique because a task appears at
 * most once in this section.
 */
export function taskTextId(taskId: number): string {
  return `dashboard-task-${taskId}-text`;
}

/**
 * What the due chip says (**W25**): `Today`, `Tomorrow`, then a short
 * absolute form.
 *
 * The two halves come from two fields and **neither is worked out here**.
 * `days_away` counts from the window's first day — which *is* `meta.anchor
 * .date`, so the chip and the page header cannot disagree — and the absolute
 * form is `due_journal.date`, a calendar day the server resolved in the same
 * zone. Subtracting one from the browser's today would be right most of the
 * time and wrong in the hours where the answer matters most.
 *
 * The relative form stops at tomorrow rather than continuing into "in 3 days".
 * The upcoming-dates chip beside it does count on, because a birthday is only
 * ever *how far off* it is; a task is due on a day the user has a journal for,
 * and past tomorrow the day itself is the more useful thing to be told.
 */
export function dueChipLabel(task: HomeDashboardTask): string {
  if (task.days_away === 0) return 'Today';
  if (task.days_away === 1) return 'Tomorrow';
  return formatIsoShortWeekdayDate(task.due_journal.date);
}
