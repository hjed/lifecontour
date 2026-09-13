/**
 * Where the keyboard goes when a dashboard show-more withdraws.
 *
 * **W28** and **W32** describe one control, not a toggle: the button unmounts
 * the moment it is pressed. An unmounted element that had focus drops it to
 * `<body>`, so a keyboard user who asked to see the rest of the week was
 * returned to the top of the document and had to traverse the whole page to
 * reach the rows they had just revealed.
 *
 * Focus goes to the **first revealed row's own first control** instead — the
 * nearest thing to where the user was, and something they can act on rather
 * than a static row made artificially focusable. Both capped sections need it
 * and neither owns its list element, which is why this reads the list rather
 * than holding a ref per row: the shell renders the `<ul>` (**W4**) and hands
 * each card a ref to it.
 */

/** What counts as a control a row can hand the keyboard to. */
const FOCUSABLE = 'a[href], button:not([disabled])';

/**
 * Focus the first control inside the row at `index`, if there is one.
 *
 * Silent when there is not: a row with nothing to act on — an upcoming date
 * whose contact link failed to render, say — should leave focus where it is
 * rather than throw inside an effect.
 */
export function focusRevealedRow(
  list: HTMLUListElement | null,
  index: number
): void {
  const row = list?.querySelectorAll('li')[index];
  row?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
}
