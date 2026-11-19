/**
 * The journal the current page is showing, read from its path.
 *
 * The New dialog sits in the top bar, outside every page, and pre-fills a
 * task's creating journal with "the journal being viewed". Reading the path
 * rather than a context set by the journal page keeps the dialog independent
 * of which pages exist: `/journals/{id}` is the one route that shows a single
 * journal. Journal ids are numeric, so the static siblings (`/journals/new`,
 * `/journals/outdoor-logbook`) and the two-segment series pages cannot match.
 */

const JOURNAL_PAGE = /^\/journals\/(\d+)$/;

/** The id of the journal at `pathname`, or `null` when it shows none. */
export function journalIdFromPath(pathname: string | null): string | null {
  return pathname?.match(JOURNAL_PAGE)?.[1] ?? null;
}
