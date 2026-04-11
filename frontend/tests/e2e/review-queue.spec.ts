import { test, expect } from './fixtures';
import { ContactTestHelpers } from './utils/test-helpers';

test.describe('Journal Review Queue', () => {
  test('should display Needs Review badge on journal list and allow resolving via sidebar', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    // Ensure we clear data before test
    await dataManager.clearAllJournals();

    // Create dates relative to today so they appear in the initial date-window
    const d = new Date();
    d.setHours(12, 0, 0, 0);
    const startStr = d.toISOString();
    d.setHours(13, 0, 0, 0);
    const endStr = d.toISOString();

    // 1. Create two test journals
    const sourceJournal = await dataManager.createJournal({
      title: 'Review Source Journal',
      content: 'I need to review this entry',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
    });

    const candidateJournal = await dataManager.createJournal({
      title: 'Candidate Duplicate',
      content: 'I am a duplicate candidate',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
    });

    // 2. Create a review item linking them
    await dataManager.createReviewItem({
      source_journal_id: Number.parseInt(sourceJournal.id),
      candidate_journal_id: Number.parseInt(candidateJournal.id),
      reason: 'duplicate_journal',
      confidence_score: 0.95,
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    // 3. Navigate to journals page
    await contactTestHelpers.navigateToAuthenticatedPage('/journals');

    // 4. Wait for the list to load and verify the "Needs Review" badge
    const sourceHeading = page.getByRole('heading', {
      name: /Review Source Journal/i,
    });
    await sourceHeading.scrollIntoViewIfNeeded();
    await expect(sourceHeading).toBeVisible({ timeout: 30000 });

    // Check for the "Needs Review" badge inside to the source journal's heading container
    await expect(sourceHeading.getByText('Needs Review')).toBeVisible();

    // 5. Open Review Queue Sidebar
    const queueBtn = page.getByRole('button', { name: /Review Queue/i });
    await expect(queueBtn).toBeVisible();
    await queueBtn.click();

    // 6. Verify sidebar content
    const sidebar = page.locator('[role="dialog"]', {
      hasText: 'Review Queue',
    });
    await expect(sidebar).toBeVisible();
    await expect(sidebar).toContainText('duplicate journal');
    await expect(sidebar).toContainText('95% Match');

    // 7. Click "Resolve Merge"
    const resolveBtn = sidebar
      .getByRole('button', { name: /Resolve Merge/i })
      .first();
    await resolveBtn.click();

    // 8. Since sourceJournalId is pre-populated, the dialog auto-advances
    //    directly to the conflict resolution step (skipping the "Next" step).
    const resolutionDialog = page.locator('[role="dialog"]', {
      hasText: 'Resolve Merge Conflicts',
    });
    await expect(resolutionDialog).toBeVisible({ timeout: 15000 });

    // 9. Close the resolution dialog via Cancel
    const cancelBtn = resolutionDialog.getByRole('button', { name: 'Cancel' });
    await cancelBtn.click();
  });

  test('should display ReviewSuggestions component on journal detail view', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    // Ensure we clear data before test
    await dataManager.clearAllJournals();

    // Create dates relative to today
    const d = new Date();
    d.setHours(12, 0, 0, 0);
    const startStr = d.toISOString();
    d.setHours(13, 0, 0, 0);
    const endStr = d.toISOString();

    // 1. Create source and candidate journals
    const sourceJournal = await dataManager.createJournal({
      title: 'Suggestion Source Journal',
      content: 'Content for detail view',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
    });

    const candidateJournal = await dataManager.createJournal({
      title: 'Detail Candidate Duplicate',
      content: 'Detail candidate content',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
    });

    // 2. Create review item
    await dataManager.createReviewItem({
      source_journal_id: Number.parseInt(sourceJournal.id),
      candidate_journal_id: Number.parseInt(candidateJournal.id),
      reason: 'duplicate_journal',
      confidence_score: 0.99,
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    // 3. Navigate directly to the journal detail view for the source
    await contactTestHelpers.navigateToAuthenticatedPage(
      `/journals/${sourceJournal.id}`
    );

    // 4. Verify the ReviewSuggestions component appears
    const suggestionsContainer = page.getByTestId(
      'review-suggestions-container'
    );
    await expect(suggestionsContainer).toBeVisible({ timeout: 15000 });
    await expect(suggestionsContainer).toContainText(
      'Detail Candidate Duplicate'
    );
    await expect(suggestionsContainer).toContainText('Confidence: 99%');

    // 5. Click "Resolve Merge"
    const resolutionButton = suggestionsContainer
      .getByRole('button', { name: /Resolve Merge/i })
      .first();
    await expect(resolutionButton).toBeVisible();
    await resolutionButton.click();

    // 6. Since sourceJournalId is pre-populated from ReviewSuggestions,
    //    the dialog auto-advances directly to Resolve Merge Conflicts.
    const resolutionDialog = page.locator('[role="dialog"]', {
      hasText: 'Resolve Merge Conflicts',
    });
    await expect(resolutionDialog).toBeVisible({ timeout: 15000 });
  });
});
