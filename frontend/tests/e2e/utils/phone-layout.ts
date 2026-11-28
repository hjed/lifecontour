import { expect, type Locator, type Page } from '@playwright/test';

/** The smallest touch target a phone layout may offer, in CSS pixels. */
export const MIN_TOUCH_TARGET = 44;

/** Layout places a 44px target on a fractional track, so compare to 0.1px. */
const toTenthPx = (px: number) => Math.round(px * 10) / 10;

async function assertTouchTarget(target: Locator): Promise<void> {
  const box = await target.boundingBox();
  expect(box).not.toBeNull();
  expect(toTenthPx(box!.width)).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
  expect(toTenthPx(box!.height)).toBeGreaterThanOrEqual(MIN_TOUCH_TARGET);
}

/**
 * Assert a target is at least 44px each way.
 *
 * Pass `retry` when the target animates in (a dialog zooming from 95% scale):
 * a box read mid-animation comes up a fraction short.
 */
export async function expectTouchTarget(
  target: Locator,
  { retry = false }: { retry?: boolean } = {}
): Promise<void> {
  if (!retry) {
    await assertTouchTarget(target);
    return;
  }
  await expect(() => assertTouchTarget(target)).toPass({ timeout: 5_000 });
}

/** Assert the page itself does not scroll sideways. */
export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth
      )
    )
    .toBe(true);
}

/**
 * Assert a control answers a touch across the 44px square around its centre,
 * for a control drawn smaller than its hit area (a checkbox whose
 * pseudo-element inset widens it), which no bounding box can measure.
 *
 * The edges and corners are probed a quarter pixel inside the square, so a
 * 42px or 43px area, or a round one, fails.
 */
export async function expectTouchHitArea(target: Locator): Promise<void> {
  const box = await target.boundingBox();
  expect(box).not.toBeNull();
  const centreX = box!.x + box!.width / 2;
  const centreY = box!.y + box!.height / 2;
  const reach = MIN_TOUCH_TARGET / 2 - 0.25;
  const offsets = [-reach, 0, reach];
  const probes = offsets
    .flatMap(dx => offsets.map(dy => [centreX + dx, centreY + dy] as const))
    .filter(([x, y]) => x !== centreX || y !== centreY);

  for (const [x, y] of probes) {
    const missedBy = await target.evaluate(
      (element, point) => {
        const hit = document.elementFromPoint(point.x, point.y);
        if (hit !== null && element.contains(hit)) return null;
        return hit === null ? 'nothing' : hit.outerHTML.slice(0, 160);
      },
      { x, y }
    );
    expect(missedBy, `a touch at (${x}, ${y}) reaches the control`).toBeNull();
  }
}
