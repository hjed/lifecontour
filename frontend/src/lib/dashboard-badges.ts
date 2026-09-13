/**
 * What a dashboard badge needs when the text inside it is the user's.
 *
 * `Badge`'s base styles are built for short, fixed labels — `whitespace-nowrap`,
 * `w-fit` and `shrink-0` between them say *"be exactly as wide as my content and
 * never give any of it back"*. That is right for a status word and wrong for
 * anything a person typed: a tag name (**W15**) or a custom important-date type
 * (**W31**) can arrive as one long unbroken token, and the badge then sizes
 * itself to that token and takes the whole row — and the page — with it.
 *
 * **The failure is clipping, not page overflow**, and getting that wrong is
 * how the first two attempts at this missed. `w-fit` is `width: fit-content`,
 * which already clamps to the space available — so the badge never pushes the
 * page sideways. What it does instead is keep `white-space: nowrap` and
 * `overflow: hidden`, and silently **cut the label off** at the column edge
 * with nothing to say it did. A `scrollWidth` measured on the page cannot see
 * that, and neither can a test that checks a class is present.
 *
 * **Two classes are load-bearing and both are easy to get wrong.**
 * `whitespace-normal` is needed because `overflow-wrap` cannot break anything
 * while a line break is forbidden. And the wrapping class has to be
 * `wrap-anywhere` (`overflow-wrap: anywhere`) rather than `break-words`
 * (`break-word`): the two behave identically once a line box exists, but only
 * `anywhere` reduces the element's **min-content** width, which is the size
 * `fit-content` is resolved against. With `break-words` the badge still asks
 * for the whole unbroken token, gets clamped, and clips exactly as before.
 *
 * `cn` resolves these against the base styles through tailwind-merge, so the
 * conflicting classes are removed rather than fighting on specificity.
 */
export const FREE_TEXT_BADGE =
  'max-w-full shrink whitespace-normal wrap-anywhere';
