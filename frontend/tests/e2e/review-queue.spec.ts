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

    // 7. Click "Confirm Match"
    const resolveBtn = sidebar
      .getByRole('button', { name: /Confirm Match/i })
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

    // 5. Click "Confirm Match"
    const resolutionButton = suggestionsContainer
      .getByRole('button', { name: /Confirm Match/i })
      .first();
    await resolutionButton.click();

    // 6. Since sourceJournalId is pre-populated from ReviewSuggestions,
    //    the dialog auto-advances directly to Resolve Merge Conflicts.
    const resolutionDialog = page.locator('[role="dialog"]', {
      hasText: 'Resolve Merge Conflicts',
    });
    await expect(resolutionDialog).toBeVisible({ timeout: 15000 });
  });

  test('should dismiss review item from sidebar and remove it from UI', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    await dataManager.clearAllJournals();

    const d = new Date();
    const startStr = d.toISOString();
    const endStr = d.toISOString();

    const sourceJournal = await dataManager.createJournal({
      title: 'Dismiss Source Journal',
      content: 'I need to review this entry',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
    });

    const candidateJournal = await dataManager.createJournal({
      title: 'Dismiss Candidate Duplicate',
      content: 'I am a duplicate candidate',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
    });

    const reviewItem = await dataManager.createReviewItem({
      source_journal_id: Number.parseInt(sourceJournal.id),
      candidate_journal_id: Number.parseInt(candidateJournal.id),
      reason: 'duplicate_journal',
      confidence_score: 0.95,
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    await contactTestHelpers.navigateToAuthenticatedPage('/journals');

    const queueBtn = page.getByRole('button', { name: /Review Queue/i });
    await expect(queueBtn).toBeVisible();
    await queueBtn.click();

    const sidebar = page.locator('[role="dialog"]', {
      hasText: 'Review Queue',
    });
    await expect(sidebar).toBeVisible();
    await expect(sidebar).toContainText('Dismiss Candidate Duplicate');

    const dismissBtn = sidebar.getByTestId(
      `queue-dismiss-btn-${reviewItem.id}`
    );
    await expect(dismissBtn).toBeVisible();
    await dismissBtn.scrollIntoViewIfNeeded();
    await expect(dismissBtn).toBeEnabled();
    // Use dispatchEvent instead of .click() as the Radix Sheet overlay and Mobile viewport
    // constraints prevent reliable bounding-box clicks even with force: true
    await dismissBtn.dispatchEvent('click');

    await expect(page.getByText('Review item dismissed')).toBeVisible();
    await expect(sidebar).not.toContainText('Dismiss Candidate Duplicate', {
      timeout: 10000,
    });

    // Also verify the list reflects the empty state or is removed
    await expect(
      sidebar.getByText('Your review queue is empty.')
    ).toBeVisible();
  });

  test('should auto-merge identical journals when Merge All Identical is clicked', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    await dataManager.clearAllJournals();

    const d = new Date();
    d.setHours(12, 0, 0, 0);
    const startStr = d.toISOString();
    d.setHours(13, 0, 0, 0);
    const endStr = d.toISOString();

    // Create two journals with IDENTICAL title, content, and date range
    const sourceJournal = await dataManager.createJournal({
      title: 'Identical Entry',
      content: 'Same content here',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
      exactTitle: true,
    });

    const candidateJournal = await dataManager.createJournal({
      title: 'Identical Entry',
      content: 'Same content here',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
      exactTitle: true,
    });

    // Create a review item linking them
    await dataManager.createReviewItem({
      source_journal_id: Number.parseInt(sourceJournal.id),
      candidate_journal_id: Number.parseInt(candidateJournal.id),
      reason: 'duplicate_journal',
      confidence_score: 0.95,
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    // Navigate to journals and open the review queue
    await contactTestHelpers.navigateToAuthenticatedPage('/journals');
    const queueBtn = page.getByRole('button', { name: /Review Queue/i });
    await expect(queueBtn).toBeVisible();
    await queueBtn.click();

    const sidebar = page.locator('[role="dialog"]', {
      hasText: 'Review Queue',
    });
    await expect(sidebar).toBeVisible();

    // Click the "Merge All Identical" button
    const autoMergeBtn = sidebar.getByTestId('auto-merge-all-btn');
    await expect(autoMergeBtn).toBeVisible();
    await autoMergeBtn.click();

    // Wait for success toast
    await expect(page.getByText(/Auto-merged 1 journal/i)).toBeVisible({
      timeout: 15000,
    });

    // The review queue should now be empty
    await expect(sidebar.getByText('Your review queue is empty.')).toBeVisible({
      timeout: 15000,
    });
  });

  test('should close merge dialog after successful merge from review queue', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    await dataManager.clearAllJournals();

    const d = new Date();
    d.setHours(12, 0, 0, 0);
    const startStr = d.toISOString();
    d.setHours(13, 0, 0, 0);
    const endStr = d.toISOString();

    // Create two journals with IDENTICAL fields (no conflicts)
    const sourceJournal = await dataManager.createJournal({
      title: 'Merge Close Source',
      content: 'Same content',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
      exactTitle: true,
    });

    const candidateJournal = await dataManager.createJournal({
      title: 'Merge Close Source',
      content: 'Same content',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
      exactTitle: true,
    });

    await dataManager.createReviewItem({
      source_journal_id: Number.parseInt(sourceJournal.id),
      candidate_journal_id: Number.parseInt(candidateJournal.id),
      reason: 'duplicate_journal',
      confidence_score: 0.85,
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    // Navigate and open review queue
    await contactTestHelpers.navigateToAuthenticatedPage('/journals');
    const queueBtn = page.getByRole('button', { name: /Review Queue/i });
    await expect(queueBtn).toBeVisible();
    await queueBtn.click();

    const sidebar = page.locator('[role="dialog"]', {
      hasText: 'Review Queue',
    });
    await expect(sidebar).toBeVisible();

    // Click "Confirm Match" to open merge dialog
    const confirmBtn = sidebar
      .getByRole('button', { name: /Confirm Match/i })
      .first();
    await confirmBtn.click();

    // Resolution dialog should appear (no conflicts → "Confirm Merge" mode)
    const resolutionDialog = page.locator('[role="dialog"]', {
      hasText: /Confirm Merge|Resolve Merge/,
    });
    await expect(resolutionDialog).toBeVisible({ timeout: 15000 });

    // Click the merge button
    const mergeBtn = resolutionDialog.getByRole('button', {
      name: /Merge/i,
    });
    await mergeBtn.click();

    // Wait for success toast
    await expect(page.getByText('Journals merged successfully')).toBeVisible({
      timeout: 15000,
    });

    // The merge resolution dialog should be closed
    await expect(resolutionDialog).not.toBeVisible({ timeout: 10000 });
  });

  test('should skip conflicting journals during auto-merge and only merge identical ones', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    await dataManager.clearAllJournals();

    const d = new Date();
    d.setHours(12, 0, 0, 0);
    const startStr = d.toISOString();
    d.setHours(13, 0, 0, 0);
    const endStr = d.toISOString();

    // Pair 1: IDENTICAL (should be auto-merged)
    const identicalSource = await dataManager.createJournal({
      title: 'AutoMerge Same',
      content: 'Same content',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
      exactTitle: true,
    });

    const identicalCandidate = await dataManager.createJournal({
      title: 'AutoMerge Same',
      content: 'Same content',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
      exactTitle: true,
    });

    // Pair 2: CONFLICTING titles (should be skipped)
    const conflictSource = await dataManager.createJournal({
      title: 'Conflict Source',
      content: 'Same content',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
    });

    const conflictCandidate = await dataManager.createJournal({
      title: 'Conflict Candidate',
      content: 'Same content',
      event_date_range: { start: startStr, end: endStr },
      types: ['note'],
    });

    // Create review items for both pairs
    await dataManager.createReviewItem({
      source_journal_id: Number.parseInt(identicalSource.id),
      candidate_journal_id: Number.parseInt(identicalCandidate.id),
      reason: 'duplicate_journal',
      confidence_score: 0.95,
    });

    await dataManager.createReviewItem({
      source_journal_id: Number.parseInt(conflictSource.id),
      candidate_journal_id: Number.parseInt(conflictCandidate.id),
      reason: 'duplicate_journal',
      confidence_score: 0.8,
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    // Navigate and open review queue
    await contactTestHelpers.navigateToAuthenticatedPage('/journals');
    const queueBtn = page.getByRole('button', { name: /Review Queue/i });
    await expect(queueBtn).toBeVisible();
    await queueBtn.click();

    const sidebar = page.locator('[role="dialog"]', {
      hasText: 'Review Queue',
    });
    await expect(sidebar).toBeVisible();

    // Click "Merge All Identical"
    const autoMergeBtn = sidebar.getByTestId('auto-merge-all-btn');
    await expect(autoMergeBtn).toBeVisible();
    await autoMergeBtn.click();

    // Should report 1 merged
    await expect(page.getByText(/Auto-merged 1 journal/i)).toBeVisible({
      timeout: 15000,
    });

    // The conflicting pair should still be in the queue
    await expect(sidebar).toContainText('Conflict', { timeout: 10000 });
  });
});
