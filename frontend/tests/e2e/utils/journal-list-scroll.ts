import { Page } from '@playwright/test';

/** Which end of the journals list to reach past. */
export type JournalListDirection = 'past' | 'future';

const SENTINEL: Record<JournalListDirection, string> = {
  past: 'journal-top-sentinel',
  future: 'journal-bottom-sentinel',
};

/** Enough to leave the sentinel's 200px observation margin in either direction. */
const WHEEL_DELTA = 600;

/**
 * Ask the journals list for entries beyond the loaded window, the way a reader
 * does: put the sentinel on screen and spin the wheel over it.
 *
 * The wheel is what makes this reliable. `scrollIntoViewIfNeeded()` — and
 * `hover()`'s implicit scroll — do nothing when the element is already on
 * screen, and the initial chunk of a sparse history routinely leaves both
 * sentinels inside the viewport with the page at the top of its scroll range.
 * No movement means no `scroll` event, and backward paging waits for the
 * reader to reach (`userHasScrolled` in `DayGroupedJournalList`), so a test
 * that scrolls only conditionally can wait forever for a page that will never
 * be fetched. A wheel event fires whether or not the page can move.
 *
 * Call it inside `expect(...).toPass()` with a short inner timeout: it is
 * idempotent, so retrying costs nothing and covers a fetch that was skipped
 * because another one was still in flight.
 */
export async function reachForMoreJournals(
  page: Page,
  direction: JournalListDirection
): Promise<void> {
  const sentinel = page.getByTestId(SENTINEL[direction]);
  await sentinel.hover();
  await page.mouse.wheel(0, direction === 'past' ? -WHEEL_DELTA : WHEEL_DELTA);
}
