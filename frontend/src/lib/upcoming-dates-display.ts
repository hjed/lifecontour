/**
 * How an upcoming contact date is worded on the dashboard (**W31**, **W32**).
 *
 * The payload deliberately ships structured values rather than finished
 * strings — a date type, a nullable year count, a day offset — so the wording
 * is a frontend concern, and this is the one place it is decided. Kept out of
 * the row for the reason `agenda-display.ts` is kept out of the agenda's: two
 * of these rules are product rules rather than formatting, and a pure function
 * lets a test assert them without rendering anything.
 *
 * **The two rules worth stating.** A `custom` date is shown under the name its
 * owner gave it and never under the word "custom", which is the database's
 * word for it and means nothing to the person reading the row. And the derived
 * age or year count is shown only where the stored precision produced one:
 * `years` is null when the date carries no year, and a badge must degrade to
 * the bare type rather than invent a number.
 */

import { ImportantDateTypeEnum } from '@/types/contacts';

/**
 * What each built-in date type is called on a badge.
 *
 * A `Record` over the enum rather than a lookup with a default, so a date type
 * added to the backend is a **compile error** here rather than a badge that
 * quietly reads "Graduation day" because nobody chose its wording.
 *
 * **The two anniversaries are written out in full**, where the wireframe's
 * sample shortens one of them to *"Anniversary"*. That sample shows a single
 * anniversary; this section shows a week of several contacts at once, and a
 * badge that could mean either a wedding or a job says nothing at all.
 */
export const DATE_TYPE_LABELS: Record<ImportantDateTypeEnum, string> = {
  [ImportantDateTypeEnum.BIRTHDAY]: 'Birthday',
  [ImportantDateTypeEnum.ANNIVERSARY_MARRIAGE]: 'Marriage anniversary',
  [ImportantDateTypeEnum.ANNIVERSARY_WORK]: 'Work anniversary',
  [ImportantDateTypeEnum.FIRST_MET]: 'First met',
  // Never reached with a name to hand — see `dateTypeLabel`, which prefers it.
  [ImportantDateTypeEnum.CUSTOM]: 'Important date',
};

/** The badge's colour per type (**W31**), from the chart palette. */
const DATE_TYPE_BADGE_CLASSES: Record<ImportantDateTypeEnum, string> = {
  [ImportantDateTypeEnum.BIRTHDAY]: 'border-chart-1 text-chart-1',
  [ImportantDateTypeEnum.ANNIVERSARY_MARRIAGE]: 'border-chart-2 text-chart-2',
  [ImportantDateTypeEnum.ANNIVERSARY_WORK]: 'border-chart-3 text-chart-3',
  [ImportantDateTypeEnum.FIRST_MET]: 'border-chart-4 text-chart-4',
  [ImportantDateTypeEnum.CUSTOM]: 'border-chart-5 text-chart-5',
};

/** Whether a wire value is one of the types this build knows how to word. */
function isKnownType(dateType: string): dateType is ImportantDateTypeEnum {
  return dateType in DATE_TYPE_LABELS;
}

/**
 * `work_anniversary` → `Work anniversary`.
 *
 * For a type the backend has grown and this build has not heard of. The row
 * still has to draw something a person can read, and the stored key is a
 * better guess at it than a blank badge or the word "Unknown".
 */
function humanise(dateType: string): string {
  const words = dateType.replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * What this kind of date is called.
 *
 * A custom date's own name wins over everything, because it is the only
 * wording that means anything to the person who chose it.
 */
export function dateTypeLabel(
  dateType: string,
  customDateTypeName: string | null
): string {
  if (customDateTypeName) return customDateTypeName;
  return isKnownType(dateType)
    ? DATE_TYPE_LABELS[dateType]
    : humanise(dateType);
}

/** The colour-coded outline classes for a type's badge (**W31**). */
export function dateTypeBadgeClassName(dateType: string): string {
  return isKnownType(dateType)
    ? DATE_TYPE_BADGE_CLASSES[dateType]
    : 'border-muted-foreground text-muted-foreground';
}

/** Just enough of an occurrence to word its badge. */
interface BadgeSubject {
  readonly date_type: string;
  readonly custom_date_type_name: string | null;
  readonly years: number | null;
}

/**
 * The badge's full text: the type, and the count this occurrence makes
 * (**W31**) — `Birthday · turns 35`, `Marriage anniversary · 34 years`.
 *
 * **`years === null` is the only thing that suppresses the suffix.** Zero is a
 * real count — a first birthday turns 0 — so a truthiness check here would
 * drop exactly the occurrence most worth noticing.
 */
export function dateBadgeLabel(date: BadgeSubject): string {
  const label = dateTypeLabel(date.date_type, date.custom_date_type_name);
  if (date.years === null) return label;

  const suffix =
    date.date_type === ImportantDateTypeEnum.BIRTHDAY
      ? `turns ${date.years}`
      : `${date.years} ${date.years === 1 ? 'year' : 'years'}`;
  return `${label} · ${suffix}`;
}

/**
 * How far off the date is, for the row's right-aligned chip (**W31**).
 *
 * The number comes from the payload and is **never** derived here: it counts
 * from the window's first day, which the server resolved in the user's
 * configured zone, and subtracting two dates in the browser's zone can answer
 * differently near midnight.
 */
export function daysAwayLabel(daysAway: number): string {
  if (daysAway === 0) return 'Today';
  if (daysAway === 1) return 'Tomorrow';
  return `in ${daysAway} days`;
}

/**
 * The show-more's text (**W32**): *"Show all 5 this week"*.
 *
 * Names the **whole window** rather than the number hidden behind the cap,
 * which is how the wireframe writes it — the useful question is how much there
 * is, not how much is missing.
 */
export function showAllLabel(total: number): string {
  return `Show all ${total} this week`;
}
