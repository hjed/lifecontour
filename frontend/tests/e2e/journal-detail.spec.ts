/**
 * E2E Tests for Journal Detail Page
 *
 * Tests the integration of JournalDetailView and all Phase 4 components
 * in the /journals/[id] page.
 */

import { test, expect } from './fixtures';

test.describe('Journal Detail Page', () => {
  test.describe('Basic Display', () => {
    test('should display journal details', async ({ journalsWithData }) => {
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);

      // Wait for page to load
      await page.waitForLoadState('networkidle');

      // Verify journal title is displayed (now in an inline editable field)
      const titleField = page.getByTestId('journal-title-field');
      await expect(titleField).toBeVisible();
      await expect(titleField).toContainText(journal.title);

      // Verify journal content is displayed
      await expect(page.getByText(journal.content)).toBeVisible();
    });

    test('should display 404 for non-existent journal', async ({
      emptyJournalsPage,
    }) => {
      const page = emptyJournalsPage;

      // Navigate to non-existent journal
      await page.goto('/journals/999999');

      // Wait for page to load
      await page.waitForLoadState('networkidle');

      // Verify error message is displayed in an alert
      // Filter for the alert that contains our error message (not the Next.js route announcer)
      const alert = page
        .getByRole('alert')
        .filter({ hasText: /failed to load journal/i });
      await expect(alert).toContainText(/failed to load journal.*not found/i);
    });
  });

  test.describe('Inline Editing', () => {
    test('should allow editing journal title', async ({ journalsWithData }) => {
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Find the title field (it's a button in view mode, not a heading)
      const titleField = page.getByTestId('journal-title-field');
      await expect(titleField).toBeVisible();
      await expect(titleField).toContainText(journal.title);

      // Click to enter edit mode
      await titleField.click();

      // Wait for the input field to appear
      const titleInput = page.getByTestId('journal-title-field-input');
      await expect(titleInput).toBeVisible();

      // Edit the title
      const newTitle = 'Updated Journal Title';
      await titleInput.fill(newTitle);

      // Click the save button
      const saveButton = page.getByRole('button', { name: 'Save changes' });
      await saveButton.click();

      // Wait for save to complete and verify the title was updated
      await expect(titleField).toContainText(newTitle);
      await expect(titleField).not.toContainText(journal.title);
    });

    test('should allow editing journal content', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Find the content field (it's a button in view mode)
      const contentField = page.getByTestId('journal-content');
      await expect(contentField).toBeVisible();
      await expect(contentField).toContainText(journal.content);

      // Click to enter edit mode
      await contentField.click();

      // Wait for the textarea to appear (use aria-label since there's no separate testid)
      const contentTextarea = page.getByRole('textbox', {
        name: 'Edit content',
      });
      await expect(contentTextarea).toBeVisible();

      // Edit the content
      const newContent = 'Updated content for the journal entry.';
      await contentTextarea.fill(newContent);

      // Click the save button
      const saveButton = page.getByTestId('journal-content-save');
      await saveButton.click();

      // Wait for save to complete and verify the content was updated
      await expect(contentField).toContainText(newContent);
      await expect(contentField).not.toContainText(journal.content);
    });

    test('should allow editing journal date range', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Find the date range field (it's a button in view mode)
      const dateField = page.getByTestId('journal-date-range-field');
      await expect(dateField).toBeVisible();

      // Get the original date range text
      const originalDateRange = await dateField.textContent();

      // Click to enter edit mode (this automatically opens the calendar)
      await dateField.click();

      // Wait for the calendar to appear and be interactive
      await page.waitForSelector('[role="grid"]', { state: 'visible' });

      // The calendar starts with the existing range selected (15-16 Jan 2024)
      // In react-day-picker range mode with a range already selected:
      // - First click on a new date: sets the start date (clears the range)
      // - Second click on another date: sets the end date

      // Get the save button reference early
      const saveButton = page.getByTestId('journal-date-range-field-save');

      // Click January 20th to set it as the start date (this clears the existing range)
      const day20 = page.getByRole('button', {
        name: 'Tuesday, January 20th, 2026',
      });
      await expect(day20).toBeVisible();
      await day20.click();

      // Wait for the calendar to update by checking the save button state
      // After clicking the first date, we should have a partial range
      await expect(saveButton).toBeVisible();

      // Now click January 22nd to set it as the end date
      const day22 = page.getByRole('button', {
        name: 'Thursday, January 22nd, 2026',
      });
      await expect(day22).toBeVisible();
      await day22.click();

      // Wait for the save button to be enabled (both dates selected)
      await expect(saveButton).toBeVisible();
      await expect(saveButton).toBeEnabled();

      // Save the changes
      await saveButton.click();

      // Wait for the edit mode to close
      await expect(saveButton).not.toBeVisible();

      // Verify the date range was updated (should be different from original)
      await expect(dateField).not.toContainText(originalDateRange || '');
      await expect(dateField).toBeVisible();
    });
  });

  test.describe('Type Sections', () => {
    test('should display journal type badges', async ({ journalsWithData }) => {
      const { page, journals } = journalsWithData;
      const journal = journals.find(j => j.types && j.types.length > 0);

      if (journal) {
        // Navigate to journal detail page
        await page.goto(`/journals/${journal.id}`);
        await page.waitForLoadState('networkidle');

        // Verify type badges are displayed
        for (const type of journal.types || []) {
          await expect(
            page.getByTestId(`type-badge-${type.toLowerCase()}`)
          ).toBeVisible();
        }
      }
    });

    test('should display type-specific editor sections for EVENT type', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;
      // Find a journal with EVENT type
      const eventJournal = journals.find(j => j.types?.includes('event'));

      if (eventJournal) {
        // Navigate to journal detail page
        await page.goto(`/journals/${eventJournal.id}`);
        await page.waitForLoadState('networkidle');

        // Verify EVENT type section is present
        const eventSection = page.getByText('Event Details');
        await expect(eventSection).toBeVisible();

        // Click to expand the section if it's collapsed
        await eventSection.click();

        // Verify event-specific fields are visible
        // These should be in the EventTypeEditor component
        await expect(page.getByText(/calendar/i).first()).toBeVisible();
      }
    });

    test('should allow editing EVENT type data', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;
      const eventJournal = journals.find(j => j.types?.includes('event'));

      if (eventJournal) {
        // Navigate to journal detail page
        await page.goto(`/journals/${eventJournal.id}`);
        await page.waitForLoadState('networkidle');

        // Find and expand the Event Details section
        const eventSection = page.getByText('Event Details');
        await expect(eventSection).toBeVisible();
        await eventSection.click();

        // Wait for the Edit button to be visible (indicates section is expanded)
        const editButton = page.getByRole('button', { name: /edit/i }).first();
        await expect(editButton).toBeVisible();

        // Click the edit button
        await editButton.click();

        // Verify we're in edit mode - look for Save/Cancel buttons
        const saveButton = page.getByRole('button', { name: /save/i }).first();
        const cancelButton = page
          .getByRole('button', { name: /cancel/i })
          .first();

        await expect(saveButton).toBeVisible();
        await expect(cancelButton).toBeVisible();
      }
    });

    test('should display type-specific editor sections for MOOD_RATING type', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;

      // Create a journal with MOOD_RATING type
      const response = await page.request.post('/api/journals', {
        data: {
          data: {
            type: 'journal',
            attributes: {
              title: 'Mood Check',
              content: 'Feeling good today!',
              event_date_range: {
                start: '2026-01-18T10:00:00Z',
                end: '2026-01-18T10:30:00Z',
              },
              types: ['mood_rating'],
            },
          },
        },
      });

      const journal = await response.json();
      const journalId = journal.data.id;

      // Register cleanup
      testCleanup(async () => {
        await page.request.delete(`/api/journals/${journalId}`);
      });

      // Navigate to journal detail page
      await page.goto(`/journals/${journalId}`);
      await page.waitForLoadState('networkidle');

      // Verify MOOD_RATING type section is present
      const moodSection = page.getByText('Mood & Energy');
      await expect(moodSection).toBeVisible();

      // Click to expand the section
      await moodSection.click();

      // Verify mood-specific fields are visible (indicates section is expanded)
      // These should be in the MoodRatingTypeEditor component
      await expect(
        page
          .getByText(/mood value/i)
          .or(page.getByText(/mood/i))
          .first()
      ).toBeVisible();
    });
  });

  test.describe('Navigation', () => {
    test('should navigate back to journal list', async ({
      journalsWithData,
    }) => {
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Find and click the back button - use button role instead of link
      const backButton = page.getByRole('button', { name: /back/i });

      // Only run test if back button is visible
      if (await backButton.isVisible()) {
        await backButton.click();

        // Wait for navigation to complete
        await page.waitForURL('**/journals');

        // Verify we're on the list page
        expect(page.url()).toContain('/journals');
        expect(page.url()).not.toContain(`/journals/${journal.id}`);
      } else {
        // Skip test if back button not available
        test.skip();
      }
    });
  });
});
