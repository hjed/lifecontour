import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Journal Merge Workflow', () => {
  test('should merge a source journal into a target journal and delete the source', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a target and a source journal
    const uniqueSuffix = Date.now().toString();
    const sourceTitle = `Source Journal ${uniqueSuffix}`;
    const targetTitle = `Target Journal ${uniqueSuffix}`;

    const journals = await dataManager.createJournals([
      {
        title: sourceTitle,
        content: 'Source interesting content',
        event_date_range: {
          start: '2026-02-10T10:00:00Z',
          end: '2026-02-10T11:00:00Z',
        },
        types: ['note'],
      },
      {
        title: targetTitle,
        content: 'Target beginning content',
        event_date_range: {
          start: '2026-02-11T14:00:00Z',
          end: '2026-02-11T15:00:00Z',
        },
        types: ['event'],
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const target = journals[1];

    // Navigate to Target Journal detail page
    await page.goto(`/journals/${target.id}`);
    await page.waitForLoadState('networkidle');

    // Ensure we are on the target page
    await expect(
      page.getByRole('heading', { name: targetTitle })
    ).toBeVisible();

    // Find and click the merge action button
    const openMergeBtn = page.getByRole('button', { name: /merge journal/i });
    await expect(openMergeBtn).toBeVisible();
    await openMergeBtn.click();

    // Ensure the dialog opens
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(page.getByText(/Merge Another Journal/i)).toBeVisible();

    // Select the source journal using the combobox
    const combobox = page.getByRole('combobox');
    await combobox.fill(sourceTitle);

    // Click the matching source journal in the dropdown
    const sourceOption = page.getByRole('option', { name: sourceTitle });
    await expect(sourceOption).toBeVisible();
    await sourceOption.click();

    // Confirm merge
    const confirmMergeBtn = page.getByRole('button', {
      name: /merge and delete source/i,
    });
    await expect(confirmMergeBtn).toBeEnabled();

    // Wait for the merge API request and response
    const mergeResponsePromise = page.waitForResponse(
      response =>
        response.url().includes(`/api/journals/${target.id}/merge`) &&
        response.request().method() === 'POST' &&
        response.status() === 200
    );

    await confirmMergeBtn.click();
    await mergeResponsePromise;

    // Verify dialog is closed
    await expect(dialog).toBeHidden();

    // Wait for the detail view to reload data or manually reload
    // In our implementation, react-query should automatically refetch after the mutation
    // Wait for the new combined content to appear
    await expect(page.getByText('Source interesting content')).toBeVisible();

    // We can also verify that the type badge from the source ('note') has been merged
    await expect(page.getByTestId('manage-type-note')).toBeVisible();
    await expect(page.getByTestId('manage-type-event')).toBeVisible();

    // Now navigate back to journals list
    await page.goto('/journals');
    await page.waitForLoadState('networkidle');

    // The target journal should still be present
    await expect(
      page.getByRole('heading', { name: targetTitle })
    ).toBeVisible();

    // But the source journal should have been deleted
    await expect(page.getByRole('heading', { name: sourceTitle })).toBeHidden();
  });
});
