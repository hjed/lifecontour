/**
 * Presentation helpers for the dashboard's agenda entries.
 *
 * The payload carries clock values (`HH:MM:SS`) in the event's own zone, and
 * the card renders them as `HH:MM – HH:MM` (**W13**). This is where the
 * seconds are dropped and the range is joined, so the row and its tests agree
 * on the one string the wireframe asks for.
 */

const CLOCK = /^(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/;

/** `HH:MM:SS` or `HH:MM` → `HH:MM`; anything else → null. */
function clockOf(value: string | null): string | null {
  if (!value) return null;
  const match = CLOCK.exec(value);
  return match ? `${match[1]}:${match[2]}` : null;
}

/**
 * The clock text for a timed entry.
 *
 * Start and end become `09:00 – 10:00`; a start with no end is shown alone;
 * no start is no time at all, which the row treats as nothing to draw rather
 * than inventing one. The dash is an en dash, as the wireframe writes it.
 */
export function formatClockRange(
  start: string | null,
  end: string | null
): string | null {
  const from = clockOf(start);
  if (!from) return null;
  const to = clockOf(end);
  return to ? `${from} – ${to}` : from;
}

/**
 * The event count beside the tomorrow disclosure (**W19**): *"2 events"*.
 *
 * Cancelled entries are counted, because the payload carries them and the row
 * they expand into shows them — a count that excluded them would disagree with
 * the list beneath it. Zero is written rather than suppressed: the disclosure
 * stays put on a clear day, so it needs an honest thing to say.
 */
export function formatEventCount(count: number): string {
  return `${count} ${count === 1 ? 'event' : 'events'}`;
}
