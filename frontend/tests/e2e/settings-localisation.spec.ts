import { test, expect } from './fixtures';
import { selectRadixOption } from './utils/radix-select';

test.describe('Settings - Localisation', () => {
  // The e2e user is shared, so every test starts and ends with no country.
  // Its timezone is left alone: it cannot be cleared again once set, and
  // other specs rely on it being unset.
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

  test('saves the default country without choosing a timezone', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await page.goto('/settings');

    const card = page.getByTestId('localisation-settings');
    const select = card.getByRole('combobox');
    await expect(select).toHaveText('None');

    await selectRadixOption(page, select, 'New Zealand');
    await expect(select).toHaveText('New Zealand');

    const saved = page.waitForResponse(
      resp =>
        resp.url().includes('/api/user-settings') &&
        resp.request().method() === 'PATCH'
    );
    await card.getByTestId('save-localisation-btn').click();
    const response = await saved;
    expect(response.ok()).toBeTruthy();
    expect(response.request().postDataJSON()).toEqual({
      default_country: 'NZ',
    });

    await page.reload();
    await expect(
      page.getByTestId('localisation-settings').getByRole('combobox')
    ).toHaveText('New Zealand');
  });
});
