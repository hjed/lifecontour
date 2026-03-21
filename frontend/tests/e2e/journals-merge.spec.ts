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
    const sharedTitle = `Shared Journal_${uniqueSuffix}`;
    const sourceTitle = sharedTitle;
    const targetTitle = sharedTitle;

    const journals = await dataManager.createJournals([
      {
        title: sharedTitle,
        content: 'Source interesting content',
        event_date_range: {
          start: '2026-02-11T14:00:00Z',
          end: '2026-02-11T15:00:00Z',
        },
        types: ['note'],
      },
      {
        title: sharedTitle,
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

    const source = journals[0];
    const target = journals[1];
    const actualSourceTitle = sharedTitle;
    const actualTargetTitle = sharedTitle;

    // Wait for the source journal to be indexed in Meilisearch
    await expect
      .poll(
        async () => {
          const response = await page.request.get(
            `/api/journals/search?q=${encodeURIComponent(actualSourceTitle)}`
          );
          if (!response.ok()) {
            return false;
          }
          const data = await response.json();
          return data.data?.some((j: any) => j.id === source.id);
        },
        {
          timeout: 15000,
        }
      )
      .toBeTruthy();

    // Navigate to Target Journal detail page
    await page.goto(`/journals/${target.id}`);
    await page.waitForLoadState('networkidle');

    // Ensure we are on the target page
    await expect(
      page.getByRole('heading', { name: actualTargetTitle })
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
    const combobox = dialog.getByRole('combobox');
    await combobox.fill(actualSourceTitle);
    await combobox.focus();
    // Click the matching source journal in the dropdown
    const sourceOption = page.locator('li[role="option"]', {
      hasText: actualSourceTitle,
    });
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
        response.request().method() === 'POST'
    );

    await confirmMergeBtn.click();
    const mergeResponse = await mergeResponsePromise;
    console.log('Merge Response Status:', mergeResponse.status());
    if (!mergeResponse.ok()) {
      console.log('Merge Error Body:', await mergeResponse.text());
    }
    expect(mergeResponse.status()).toBe(200);

    // Verify dialog is closed
    await expect(dialog).toBeHidden();

    // Wait for the detail view to reload data or manually reload
    // In our implementation, react-query should automatically refetch after the mutation
    // Wait for the new combined content to appear
    await expect(page.getByTestId('journal-content')).toContainText(
      'Source interesting content'
    );

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
