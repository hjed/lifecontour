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
 * **`:scope >` is load-bearing.** A section's rows nest lists of their own — a
 * task row draws its linked contacts as a `ul` of `li`s (**W27**), an agenda
 * row its participant stack — so an unscoped `querySelectorAll('li')` counts
 * those too and indexes into the wrong row the moment any row above the cap
 * has one. Focus would then land on an earlier row, or on a contact `li` with
 * no control in it and so nowhere at all. Raised by review on PR #1435; the
 * first version of the test could not catch it because every task in the
 * fixture had an empty `contacts` list.
 *
 * Silent when the row holds no control: a row with nothing to act on should
 * leave focus where it is rather than throw inside an effect.
 */
export function focusRevealedRow(
  list: HTMLUListElement | null,
  index: number
): void {
  const row = list?.querySelectorAll<HTMLLIElement>(':scope > li')[index];
  row?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
}
