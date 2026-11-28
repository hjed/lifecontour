import type { Page } from '@playwright/test';

import { test, expect } from './fixtures';
import {
  expectNoHorizontalScroll,
  expectTouchTarget,
} from './utils/phone-layout';

/**
 * The task icon picker, in a real browser, before any product page embeds it.
 *
 * `/e2e-harness/task-icon-picker` renders the picker on its own beside an
 * `<output>` of the value it last handed back; only the Playwright server
 * serves it (`E2E_TEST_ROUTES`). The harness holds its own state, so every
 * test starts from "No icon" and needs no seeded data.
 */

const HARNESS = '/e2e-harness/task-icon-picker';
/** The `gap-2` between the search field and its status message. */
const ROW_GAP = 8;

async function openPicker(page: Page) {
  await page.goto(HARNESS);
  await expect(page.getByTestId('task-icon-picker-harness')).toHaveAttribute(
    'data-hydrated',
    'true'
  );
}

const iconGroup = (page: Page) =>
  page.getByRole('radiogroup', { name: 'Icon' });
const searchField = (page: Page) =>
  page.getByRole('searchbox', { name: 'Search icons' });
const chosenValue = (page: Page) =>
  page.getByRole('status', { name: 'Chosen icon value' });
const pickerText = (page: Page, text: string) =>
  page.getByTestId('task-icon-picker-harness').getByText(text, { exact: true });
const tile = (page: Page, name: string) =>
  iconGroup(page).getByRole('radio', { name, exact: true });

/**
 * Radix moves focus on a timeout after the keydown, and an arrow checks the
 * radio it lands on only while the key is still down. A person's keypress
 * outlasts that timeout; Playwright's default press does not.
 */
const ARROW_HOLD = { delay: 50 };

test.describe('Task icon picker', () => {
  test('finds an icon by name and chooses it', async ({ page }) => {
    await openPicker(page);

    await searchField(page).fill('tent');
    await expect(iconGroup(page).getByRole('radio')).toHaveCount(2);
    await expect(pickerText(page, '1 icon')).toBeVisible();

    await tile(page, 'Tent').click();

    await expect(tile(page, 'Tent')).toBeChecked();
    await expect(chosenValue(page)).toHaveText('tent');
    await expect(pickerText(page, 'Chosen: Tent')).toBeVisible();
  });

  test('"No icon" clears a chosen icon', async ({ page }) => {
    await openPicker(page);
    await tile(page, 'Tent').click();
    await expect(chosenValue(page)).toHaveText('tent');

    await searchField(page).fill('zzz');
    await expect(pickerText(page, 'No icons match "zzz"')).toBeVisible();
    await tile(page, 'No icon').click();

    await expect(tile(page, 'No icon')).toBeChecked();
    await expect(chosenValue(page)).toHaveText('none');
  });

  test('is operable from the keyboard alone', async ({ page }) => {
    await openPicker(page);

    await searchField(page).focus();
    await page.keyboard.press('Tab');
    await expect(tile(page, 'No icon')).toBeFocused();
    await expect(tile(page, 'No icon')).toBeChecked();
    await expect(tile(page, 'No icon')).toHaveCSS('outline-style', 'solid');

    await page.keyboard.press('ArrowRight', ARROW_HOLD);
    await expect(tile(page, 'List')).toBeChecked();
    await expect(chosenValue(page)).toHaveText('list');

    await page.keyboard.press('End');
    await expect(tile(page, 'Camera')).toBeFocused();
    await page.keyboard.press('Space');
    await expect(tile(page, 'Camera')).toBeChecked();
    await expect(chosenValue(page)).toHaveText('camera');
  });

  test('scrolls the grid to reach the rest of the set', async ({ page }) => {
    await openPicker(page);
    const grid = iconGroup(page);

    const before = await grid.evaluate(el => ({
      scrollTop: el.scrollTop,
      overflows: el.scrollHeight > el.clientHeight,
    }));
    expect(before).toEqual({ scrollTop: 0, overflows: true });
    await expect(tile(page, 'Camera')).not.toBeInViewport();

    await tile(page, 'Camera').scrollIntoViewIfNeeded();

    await expect(tile(page, 'Camera')).toBeInViewport();
    expect(await grid.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test('has no horizontal scroll and 44px targets', async ({ page }) => {
      await openPicker(page);

      await expectNoHorizontalScroll(page);

      await expectTouchTarget(searchField(page));
      const tiles = iconGroup(page).getByRole('radio');
      await expect(tiles).toHaveCount(41);
      for (const target of await tiles.all()) {
        await expectTouchTarget(target);
      }
    });

    test('keeps the search field usable when a long search matches nothing', async ({
      page,
    }) => {
      await openPicker(page);
      const query = 'a-very-long-search-that-matches-no-icon-at-all';

      await searchField(page).fill(query);

      const message = pickerText(page, `No icons match "${query}"`);
      await expect(message).toBeVisible();
      const field = await searchField(page).boundingBox();
      const beside = await message.boundingBox();
      expect(field).not.toBeNull();
      expect(beside).not.toBeNull();
      expect(field!.width).toBeGreaterThanOrEqual(beside!.width - ROW_GAP);
      await expectTouchTarget(searchField(page));
      const overflow = await message.evaluate(el => ({
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
      }));
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);
    });
  });
});
