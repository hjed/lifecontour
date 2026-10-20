import { test, expect } from './fixtures';

test.describe('Settings - Default Country', () => {
  // The e2e user is shared, so every test starts and ends with no country.
  test.beforeEach(async ({ authenticatedPage }) => {
    const res = await authenticatedPage.request.patch('/api/user-settings', {
      data: { default_country: null },
    });
    expect(res.ok()).toBeTruthy();
  });

  test.afterEach(async ({ authenticatedPage }) => {
    await authenticatedPage.request.patch('/api/user-settings', {
      data: { default_country: null },
    });
  });

  test('saves the default country and keeps it across a reload', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await page.goto('/settings');

    const card = page.getByTestId('default-country-settings');
    const select = card.getByRole('combobox');
    await expect(select).toHaveText('None');

    await select.click();
    await page.getByRole('option', { name: 'New Zealand' }).click();
    await expect(select).toHaveText('New Zealand');

    const saved = page.waitForResponse(
      resp =>
        resp.url().includes('/api/user-settings') &&
        resp.request().method() === 'PATCH'
    );
    await card.getByTestId('save-default-country-btn').click();
    expect((await saved).ok()).toBeTruthy();

    await page.reload();
    await expect(
      page.getByTestId('default-country-settings').getByRole('combobox')
    ).toHaveText('New Zealand');
  });
});
