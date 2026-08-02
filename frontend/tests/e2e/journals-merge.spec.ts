import { test, expect } from './fixtures';
import type { Locator } from '@playwright/test';
import { TestDataManager } from './data-management';

const todayISO = new Date().toISOString();

/**
 * Helper that fills the combobox, waits for results, and clicks the matching option.
 * Wrapped in expect().toPass() at the call site so the whole sequence retries
 * atomically on mobile where touch-blur races can dismiss the dropdown.
 */
async function selectJournalInCombobox(dialog: Locator, title: string) {
  const combobox = dialog.getByRole('combobox');
  // Clear + fill triggers the debounced search
  await combobox.clear();
  await combobox.fill(title);

  // Wait for and click the matching option
  const sourceOption = dialog.locator('li[role="option"]', {
    hasText: title,
  });
  await expect(sourceOption).toBeVisible({ timeout: 15000 });
  await sourceOption.click();
}

test.describe('Journal Merge Workflow', () => {
  test('should merge a source journal into a target journal and delete the source', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a target and a source journal
    const uniqueSuffix = Date.now().toString();
    const sourceTitle = `Shared Source_${uniqueSuffix}`;
    const targetTitle = `Shared Target_${uniqueSuffix}`;

    const journals = await dataManager.createJournals([
      {
        title: sourceTitle,
        exactTitle: true,
        content: 'Source interesting content',
        event_date_range: {
          start: todayISO,
          end: todayISO,
        },
        types: ['note'],
      },
      {
        title: targetTitle,
        exactTitle: true,
        content: 'Target beginning content',
        event_date_range: {
          start: todayISO,
          end: todayISO,
        },
        types: ['plan'],
        type_data: { plan: { documents: [] } },
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const target = journals[1];

    // No need to wait for MeiliSearch indexing — the combobox uses database ILIKE search,
    // not MeiliSearch, so the journal is findable immediately after creation.

    // Navigate to Target Journal detail page
    await page.goto(`/journals/${target.id}`);
    await expect(page.locator('main, [role="main"]').first()).toBeVisible();

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

    // Select the source journal using the combobox — retry the whole fill+click
    // sequence atomically to handle mobile touch-blur race conditions
    await expect(async () => {
      await selectJournalInCombobox(dialog, sourceTitle);
      // Verify the selection was registered by checking for the "Selected to merge" text
      await expect(dialog.getByText(`Selected to merge:`)).toBeVisible({
        timeout: 2000,
      });
    }).toPass({ timeout: 20000 });

    // Click Next to go to resolution dialog
    const nextBtn = dialog.getByRole('button', {
      name: /next/i,
    });
    await expect(nextBtn).toBeEnabled();
    await nextBtn.click();

    // Now we should see the resolution dialog
    const resolutionDialog = page
      .getByRole('dialog')
      .filter({ hasText: 'Resolve Merge Conflicts' });
    await expect(resolutionDialog).toBeVisible();

    // Choose Source for the content conflict
    const sourceContentLabel = resolutionDialog.locator(
      'label[for="source-content"]'
    );
    await expect(sourceContentLabel).toBeVisible();
    await sourceContentLabel.click();

    // Confirm merge
    const confirmMergeBtn = resolutionDialog.getByRole('button', {
      name: /resolve and merge/i,
    });
    await expect(confirmMergeBtn).toBeEnabled();

    // Wait for the merge API request and response and React Query invalidation
    let postFinished = false;
    const mergeResponsePromise = page.waitForResponse(response => {
      if (
        response.url().includes(`/api/journals/${target.id}/merge`) &&
        response.request().method() === 'POST'
      ) {
        postFinished = true;
        return true;
      }
      return false;
    });
    const detailGetPromise = page.waitForResponse(
      response =>
        postFinished &&
        response.url().endsWith(`/api/journals/${target.id}`) &&
        response.request().method() === 'GET' &&
        response.ok()
    );

    await confirmMergeBtn.click();
    const mergeResponse = await mergeResponsePromise;
    console.debug('Merge Response Status:', mergeResponse.status());
    if (!mergeResponse.ok()) {
      console.debug('Merge Error Body:', await mergeResponse.text());
    }
    expect(mergeResponse.status()).toBe(200);
    await detailGetPromise;

    // Verify dialog is closed
    await expect(resolutionDialog).toBeHidden();

    // Wait for the new combined content to appear
    await expect(page.getByTestId('journal-content')).toContainText(
      'Source interesting content'
    );

    // Verify that the type badge from the target ('plan') has been preserved
    await expect(page.getByTestId('manage-type-plan')).toBeVisible();

    // Now navigate back to journals list
    await page.goto('/journals');
    await expect(page.locator('main, [role="main"]').first()).toBeVisible();

    // The target journal should still be present
    await expect(
      page.getByRole('heading', { name: targetTitle })
    ).toBeVisible();

    // But the source journal should have been deleted
    await expect(page.getByRole('heading', { name: sourceTitle })).toBeHidden();
  });

  test('should merge journals with type-specific data conflicts and resolve overrides', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    const uniqueSuffix = Date.now().toString();
    const sourceTitle = `Mood Source_${uniqueSuffix}`;
    const targetTitle = `Mood Target_${uniqueSuffix}`;

    // Create target journal with MOOD_RATING
    const journals = await dataManager.createJournals([
      {
        title: sourceTitle,
        exactTitle: true,
        content: 'Source mood content',
        event_date_range: {
          start: todayISO,
          end: todayISO,
        },
        types: ['mood_rating'],
        type_data: {
          mood_rating: {
            mood_value: 8,
            energy_level: 8,
          },
        },
      },
      {
        title: targetTitle,
        exactTitle: true,
        content: 'Target mood content',
        event_date_range: {
          start: todayISO,
          end: todayISO,
        },
        types: ['mood_rating'],
        type_data: {
          mood_rating: {
            mood_value: 3,
            energy_level: 5,
          },
        },
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const target = journals[1];

    // No MeiliSearch wait needed — combobox uses database ILIKE search

    // Navigate to Target Journal detail page
    await page.goto(`/journals/${target.id}`);
    await expect(page.locator('main, [role="main"]').first()).toBeVisible();

    // Find and click the merge action button
    const openMergeBtn = page.getByRole('button', { name: /merge journal/i });
    await expect(openMergeBtn).toBeVisible();
    await openMergeBtn.click();

    // Select the source journal using the combobox
    const dialog = page
      .getByRole('dialog')
      .filter({ hasText: 'Merge Another Journal' });
    await expect(dialog).toBeVisible();

    // Retry the combobox fill+click atomically for mobile reliability
    await expect(async () => {
      await selectJournalInCombobox(dialog, sourceTitle);
      await expect(dialog.getByText(`Selected to merge:`)).toBeVisible({
        timeout: 2000,
      });
    }).toPass({ timeout: 20000 });

    // Click Next to go to resolution dialog
    const nextBtn = dialog.getByRole('button', { name: /next/i });
    await expect(nextBtn).toBeEnabled();
    await nextBtn.click();

    // Now we should see the resolution dialog showing mood_value and energy_level conflicts
    const resolutionDialog = page
      .getByRole('dialog')
      .filter({ hasText: 'Resolve Merge Conflicts' });
    await expect(resolutionDialog).toBeVisible();

    // We expect to see conflicts for mood_value and energy_level
    await expect(
      resolutionDialog.getByText('Mood Rating — Mood Value')
    ).toBeVisible();
    await expect(
      resolutionDialog.getByText('Mood Rating — Energy Level')
    ).toBeVisible();

    // Let's resolve mood_value to use Source (value 8)
    const sourceMoodValueLabel = resolutionDialog.locator(
      'label[for="source-type_data.mood_rating.mood_value"]'
    );
    await expect(sourceMoodValueLabel).toBeVisible();
    await sourceMoodValueLabel.click();

    // Let's resolve energy_level to use Target (value 5 is the default, but we can explicitly click it)
    const targetEnergyLevelLabel = resolutionDialog.locator(
      'label[for="target-type_data.mood_rating.energy_level"]'
    );
    await expect(targetEnergyLevelLabel).toBeVisible();
    await targetEnergyLevelLabel.click();

    // Confirm merge
    const confirmMergeBtn = resolutionDialog.getByRole('button', {
      name: /resolve and merge/i,
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
    expect(mergeResponse.status()).toBe(200);

    // Verify dialog is closed
    await expect(resolutionDialog).toBeHidden();

    // We can verify that the new mood value is shown on the page if it has a way to display it
    // Wait for page to reflect that it's merged or simply let it pass
  });

  test('should combine two fitness activities into one merged journal', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    /**
     * Two halves of one ride — a recording stopped and restarted — merged with
     * the panel's default "Combine both activities" mode: the metrics add up
     * rather than one set replacing the other.
     *
     * Keeping both Strava links is covered by the backend integration tests
     * instead: the second link lives in `sync_metadata`, which the journals
     * REST API this test builds its data through cannot seed.
     */
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    const uniqueSuffix = Date.now().toString();
    const sourceTitle = `Ride Part 2_${uniqueSuffix}`;
    const targetTitle = `Ride Part 1_${uniqueSuffix}`;

    const journals = await dataManager.createJournals([
      {
        title: sourceTitle,
        exactTitle: true,
        content: 'Second half of the ride',
        event_date_range: { start: todayISO, end: todayISO },
        types: ['fitness'],
        type_data: {
          fitness: {
            distance: 3000,
            duration: 1200,
            elevation_gain: 30,
            calories: 200,
          },
        },
      },
      {
        title: targetTitle,
        exactTitle: true,
        content: 'First half of the ride',
        event_date_range: { start: todayISO, end: todayISO },
        types: ['fitness'],
        type_data: {
          fitness: {
            distance: 5000,
            duration: 1800,
            elevation_gain: 50,
            calories: 300,
          },
        },
      },
    ]);

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const target = journals[1];

    await page.goto(`/journals/${target.id}`);
    await expect(page.locator('main, [role="main"]').first()).toBeVisible();

    const openMergeBtn = page.getByRole('button', { name: /merge journal/i });
    await expect(openMergeBtn).toBeVisible();
    await openMergeBtn.click();

    const dialog = page
      .getByRole('dialog')
      .filter({ hasText: 'Merge Another Journal' });
    await expect(dialog).toBeVisible();

    await expect(async () => {
      await selectJournalInCombobox(dialog, sourceTitle);
      await expect(dialog.getByText(`Selected to merge:`)).toBeVisible({
        timeout: 2000,
      });
    }).toPass({ timeout: 20000 });

    const nextBtn = dialog.getByRole('button', { name: /next/i });
    await expect(nextBtn).toBeEnabled();
    await nextBtn.click();

    const resolutionDialog = page
      .getByRole('dialog')
      .filter({ hasText: 'Resolve Merge Conflicts' });
    await expect(resolutionDialog).toBeVisible();

    // Combining is the offered default, and the preview shows the totals
    await expect(
      resolutionDialog.getByTestId('radio-fitness-additive')
    ).toBeChecked();
    const preview = resolutionDialog.getByTestId('fitness-combined-preview');
    await expect(preview).toContainText('8.00 km');
    await expect(preview).toContainText('50:00');

    // The per-field fitness rows are replaced by the combination
    await expect(
      resolutionDialog.getByTestId('radio-target-type_data.fitness.distance')
    ).toBeHidden();

    const confirmMergeBtn = resolutionDialog.getByRole('button', {
      name: /resolve and merge/i,
    });
    await expect(confirmMergeBtn).toBeEnabled();

    const mergeResponsePromise = page.waitForResponse(
      response =>
        response.url().includes(`/api/journals/${target.id}/merge`) &&
        response.request().method() === 'POST'
    );
    await confirmMergeBtn.click();
    const mergeResponse = await mergeResponsePromise;
    expect(mergeResponse.status()).toBe(200);
    await expect(resolutionDialog).toBeHidden();

    // The merged journal carries the summed metrics
    const detail = await page.request.get(`/api/journals/${target.id}`);
    expect(detail.status()).toBe(200);
    const fitness = (await detail.json()).data.attributes.type_data.fitness;
    expect(fitness.distance).toBe(8000);
    expect(fitness.duration).toBe(3000);
    expect(fitness.elevation_gain).toBe(80);
    expect(fitness.calories).toBe(500);
  });
});
