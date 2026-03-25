import { test, expect } from './fixtures';
import { FRONTEND_TEST_URL } from './utils/frontend-test-config';

test.describe('Journal Hierarchy', () => {
  // Helper to ensure clean slate
  test.afterEach(async ({ request }) => {
    try {
      // Find all journals starting with 'E2E Hierarchy' and delete them using API
      const searchResponse = await request.get(
        `${FRONTEND_TEST_URL}/api/journals?search=E2E Hierarchy`
      );
      if (searchResponse.ok()) {
        const body = await searchResponse.json();
        for (const journal of body.data) {
          await request.delete(
            `${FRONTEND_TEST_URL}/api/journals/${journal.id}`
          );
        }
      }
    } catch (e) {
      console.debug('Cleanup failed:', e);
    }
  });

  test('should create a child journal and display the parent reference', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    // 1. Create the parent journal via API to save time (or UI, but UI is fine)
    const parentTitle = `E2E Hierarchy Parent - ${Date.now()}`;
    await page.goto('/journals/new');
    await page.waitForLoadState('networkidle');

    await page.getByLabel(/title/i).fill(parentTitle);
    await page.getByLabel(/content/i).fill('This is the parent journal.');

    // Wait for the API response
    const parentResponsePromise = page.waitForResponse(
      response =>
        response.url().includes('/api/journals') &&
        response.request().method() === 'POST' &&
        response.status() === 201
    );

    const createButton = page.getByRole('button', { name: /create journal/i });
    await expect(createButton).toBeEnabled();
    await createButton.click();
    await parentResponsePromise;

    // Wait for redirect to detail page
    await page.waitForURL(/\/journals\/\d+/);

    // Save parent ID from URL
    const parentUrl = page.url();
    const match = parentUrl.match(/\/journals\/(\d+)/);
    expect(match).not.toBeNull();
    const parentId = match![1];

    // Ensure parent journal was fully indexed by meilisearch so combobox finds it
    await page.waitForTimeout(1500);

    // 2. Create the child journal
    const childTitle = `E2E Hierarchy Child - ${Date.now()}`;
    await page.goto('/journals/new');
    await page.waitForLoadState('networkidle');

    // Fill basic details
    await page.getByLabel(/title/i).fill(childTitle);
    await page.getByLabel(/content/i).fill('This is the child journal.');

    // Select parent journal using combobox
    // The placeholder is 'Search for a parent journal...'
    await page.fill(
      'input[placeholder="Search for a parent journal..."]',
      'E2E Hierarchy Parent'
    );

    // Wait for dropdown to show parent journal
    const parentOption = page.getByRole('option', { name: parentTitle });
    await expect(parentOption).toBeVisible({ timeout: 5000 });
    await parentOption.click();

    // Wait for the API response
    const childResponsePromise = page.waitForResponse(
      response =>
        response.url().includes('/api/journals') &&
        response.request().method() === 'POST' &&
        response.status() === 201
    );

    const childCreateButton = page.getByRole('button', {
      name: /create journal/i,
    });
    await expect(childCreateButton).toBeEnabled();
    await childCreateButton.click();
    await childResponsePromise;

    // 3. Verify parent breadcrumb on descendant's detail page
    await page.waitForURL(/\/journals\/\d+/);
    await expect(
      page.getByRole('heading', { name: childTitle, exact: true }).first()
    ).toBeVisible();

    const parentLink = page.getByTestId('parent-link');
    await expect(parentLink).toBeVisible();
    await expect(parentLink).toHaveText(parentTitle);
    await expect(parentLink).toHaveAttribute('href', `/journals/${parentId}`);

    // Click parent breadcrumb to verify navigation
    await parentLink.click();
    await page.waitForURL(/\/journals\/\d+/);
    await expect(
      page.getByRole('heading', { name: parentTitle, exact: true }).first()
    ).toBeVisible();

    // 4. Verify child journal appears in parent's children list
    const childLink = page.getByRole('link', { name: childTitle });
    await expect(childLink).toBeVisible();
  });
});
