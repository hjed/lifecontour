import { expect, type Page } from '@playwright/test';

export type CalendarViewName = 'Month' | 'Week' | 'Day' | 'Agenda';

/**
 * Switch the /journals view mode and wait until that view has rendered.
 *
 * A single click on the view radio can be swallowed while the journals page
 * settles after `journals-list-ready`: Playwright reports the click done, no
 * handler runs, and List view stays checked (seen on Firefox in CI). The click
 * is level-triggered on the radio's own `aria-checked`, so it is retried only
 * while the view is not yet selected and a landed click is never repeated.
 * Selecting a view is idempotent, so a retry cannot toggle it back.
 */
export async function selectCalendarView(
  page: Page,
  view: CalendarViewName
): Promise<void> {
  const radio = page
    .getByRole('radiogroup', { name: 'View mode' })
    .getByRole('radio', { name: `${view} view` });

  await expect(async () => {
    if ((await radio.getAttribute('aria-checked')) !== 'true') {
      await radio.click({ timeout: 2000 });
    }
    await expect(radio).toHaveAttribute('aria-checked', 'true', {
      timeout: 2000,
    });
  }).toPass({ timeout: 15000 });

  await expect(
    page.getByTestId(`calendar-${view.toLowerCase()}-view`)
  ).toBeVisible();
}

/**
 * Open /journals, wait for the list to settle, then switch to `view`.
 *
 * `journals-list-ready` is the only safe gate before clicking on this page:
 * earlier landmarks resolve while the list is still scrolling itself to today.
 */
export async function openJournalsInView(
  page: Page,
  view: CalendarViewName
): Promise<void> {
  await page.goto('/journals');
  await expect(page.getByTestId('journals-list-ready')).toBeVisible();
  await selectCalendarView(page, view);
}
