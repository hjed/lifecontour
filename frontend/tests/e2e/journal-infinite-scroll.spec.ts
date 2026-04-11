import { test, expect } from './fixtures';

test.describe('Journal Infinite Scroll', () => {
  test('should load past and future journals seamlessly', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );

    // Clear existing data
    await dataManager.clearAllJournals();

    // Calculate dates
    const today = new Date();

    const pastDate = new Date(today);
    pastDate.setDate(today.getDate() - 7);

    const futureDate = new Date(today);
    futureDate.setDate(today.getDate() + 7);

    // Create 3 journals spaced apart > chunk size (7 days)
    await dataManager.createJournals([
      {
        title: 'Present Journal',
        content: 'This happened today',
        event_date_range: {
          start: today.toISOString(),
          end: today.toISOString(),
        },
      },
      {
        title: 'Past Journal',
        content: 'This happened 7 days ago',
        event_date_range: {
          start: pastDate.toISOString(),
          end: pastDate.toISOString(),
        },
      },
      {
        title: 'Future Journal',
        content: 'This will happen 7 days in future',
        event_date_range: {
          start: futureDate.toISOString(),
          end: futureDate.toISOString(),
        },
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // 1. Visit page
    await page.goto('/journals');
    await expect(page.getByTestId('journals-list-ready')).toBeVisible();
    await page.waitForLoadState('networkidle');

    // 2. Initial state: Present should be visible, others shouldn't
    await expect(
      page.getByRole('heading', { name: /Present Journal/i })
    ).toBeVisible();
    await expect(
      page.getByRole('heading', { name: /Past Journal/i })
    ).not.toBeVisible();

    // 3. Scroll Down (to FUTURE) -> Should trigger fetchNextPage
    const bottomSentinel = page.getByTestId('journal-bottom-sentinel');
    await expect(bottomSentinel).toBeVisible();

    // Smooth scroll into view might not always trigger intersection observer immediately in headless,
    // force it by evaluating scroll
    await bottomSentinel.scrollIntoViewIfNeeded();

    // Wait for the future journal to appear
    await expect(
      page.getByRole('heading', { name: /Future Journal/i })
    ).toBeVisible({ timeout: 15000 });

    // 4. Scroll Up (to PAST) -> Should trigger fetchPreviousPage
    const topSentinel = page.getByTestId('journal-top-sentinel');
    await expect(topSentinel).toBeVisible();

    // Use evaluate directly to scroll to the very top to hit the sentinel reliably
    await page.evaluate(() => window.scrollTo(0, 0));

    // Wait for the past journal to appear
    await expect(
      page.getByRole('heading', { name: /Past Journal/i })
    ).toBeVisible({ timeout: 15000 });
  });
});
