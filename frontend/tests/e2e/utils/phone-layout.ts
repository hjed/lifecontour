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
