import { test, expect } from './fixtures';

/**
 * The colour palette is saved on the account and painted as `data-palette`
 * on <html>; light/dark stays with next-themes' `.dark` class. The e2e user
 * is shared, so every test starts and ends on the default palette.
 */
test.describe('Settings - Appearance', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    const res = await authenticatedPage.request.patch('/api/user-settings', {
      data: { theme_palette: null },
    });
    expect(res.ok()).toBeTruthy();
  });

  test.afterEach(async ({ authenticatedPage }) => {
    await authenticatedPage.request.patch('/api/user-settings', {
      data: { theme_palette: null },
    });
  });

  test('picking Emerald repaints the app and saves it to the account', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await page.goto('/settings');
    const html = page.locator('html');
    const card = page.getByTestId('appearance-settings');
    const defaultPrimary = await html.evaluate(el =>
      getComputedStyle(el).getPropertyValue('--primary').trim()
    );

    const saved = page.waitForResponse(
      resp =>
        resp.url().includes('/api/user-settings') &&
        resp.request().method() === 'PATCH'
    );
    await card.getByRole('radio', { name: /emerald/i }).click();
    const response = await saved;
    expect(response.ok()).toBeTruthy();
    expect(response.request().postDataJSON()).toEqual({
      theme_palette: 'emerald',
    });

    await expect(html).toHaveAttribute('data-palette', 'emerald');
    const emeraldPrimary = await html.evaluate(el =>
      getComputedStyle(el).getPropertyValue('--primary').trim()
    );
    expect(emeraldPrimary).not.toBe(defaultPrimary);

    await page.reload();
    await expect(html).toHaveAttribute('data-palette', 'emerald');
    await expect(
      page
        .getByTestId('appearance-settings')
        .getByRole('radio', { name: /emerald/i })
    ).toBeChecked();
  });

  test('the account palette follows the user to a fresh browser', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const res = await page.request.patch('/api/user-settings', {
      data: { theme_palette: 'emerald' },
    });
    expect(res.ok()).toBeTruthy();

    // A browser that has never cached a palette: only the account knows.
    await page.goto('/settings');
    await page.evaluate(() => localStorage.clear());
    await page.reload();

    await expect(page.locator('html')).toHaveAttribute(
      'data-palette',
      'emerald'
    );
  });

  test('the in-app Dark mode wins over a light OS, in either palette', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const res = await page.request.patch('/api/user-settings', {
      data: { theme_palette: 'emerald' },
    });
    expect(res.ok()).toBeTruthy();
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto('/settings');
    const html = page.locator('html');
    await expect(html).toHaveAttribute('data-palette', 'emerald');
    const lightBackground = await html.evaluate(el =>
      getComputedStyle(el).getPropertyValue('--background').trim()
    );

    // The header toggle flips the `.dark` class in one click.
    const toggle = page.getByTestId('theme-toggle');
    await toggle.click();

    await expect(html).toHaveClass(/\bdark\b/);
    await expect(html).toHaveAttribute('data-palette', 'emerald');
    await expect
      .poll(() =>
        html.evaluate(el =>
          getComputedStyle(el).getPropertyValue('--background').trim()
        )
      )
      .not.toBe(lightBackground);
    // `dark:` utilities follow the app's mode, not the (light) OS: the moon
    // glyph is shown by `dark:scale-100`, hidden by `scale-0` otherwise.
    const moon = toggle.locator('svg').nth(1);
    await expect
      .poll(() => moon.evaluate(el => getComputedStyle(el).scale))
      .toMatch(/^1( 1)?$/);
  });
});
