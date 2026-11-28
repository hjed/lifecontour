/**
 * Proving a task row shows all of itself on a narrow screen.
 *
 * The journal and dashboard task rows are `overflow-hidden` (their accent bar
 * is clipped to the rounded corner), so a layout that breaks inside a row cuts
 * its content off rather than widening the page: a page-width check alone
 * passes over it. These read the row's own boxes instead.
 */

import { expect, type Locator } from '@playwright/test';

/** The text is not cut off inside its own box. */
export async function expectTextNotClipped(text: Locator): Promise<void> {
  const widths = await text.evaluate(element => ({
    scrollWidth: element.scrollWidth,
    clientWidth: element.clientWidth,
  }));
  expect(widths.scrollWidth).toBeLessThanOrEqual(widths.clientWidth);
}

/** Each part lies wholly inside the row, so the row's clip hides none of it. */
export async function expectInsideRow(
  row: Locator,
  parts: readonly Locator[]
): Promise<void> {
  const rowBox = await row.boundingBox();
  expect(rowBox).not.toBeNull();
  for (const part of parts) {
    const box = await part.boundingBox();
    expect(box).not.toBeNull();
    // Compared to 0.1px: fractional layout puts edges a hair either side.
    expect(box!.x).toBeGreaterThanOrEqual(rowBox!.x - 0.1);
    expect(box!.y).toBeGreaterThanOrEqual(rowBox!.y - 0.1);
    expect(box!.x + box!.width).toBeLessThanOrEqual(
      rowBox!.x + rowBox!.width + 0.1
    );
    expect(box!.y + box!.height).toBeLessThanOrEqual(
      rowBox!.y + rowBox!.height + 0.1
    );
  }
}
