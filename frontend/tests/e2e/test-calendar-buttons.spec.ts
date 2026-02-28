import { test } from './fixtures';
test('log calendar buttons', async ({ authenticatedPage }) => {
  const page = authenticatedPage;
  await page.goto('/journals');
  await page.waitForLoadState('networkidle');
  const dateRangeButton = page.getByRole('button', {
    name: /pick a date range/i,
  });
  await dateRangeButton.click();
  await page.waitForSelector('[role="grid"]', { state: 'visible' });
  const buttons = await page.getByRole('button').all();
  for (const b of buttons) {
    const text = await b.textContent();
    const ariaLabel = await b.getAttribute('aria-label');
    console.log(`Button text: "${text}", aria-label: "${ariaLabel}"`);
  }
});
