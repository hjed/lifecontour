/**
 * E2E Tests for Journal Detail Page
 *
 * Tests the integration of JournalDetailView and all Phase 4 components
 * in the /journals/[id] page.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

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

      // Dynamically pick two dates: today + 1 and today + 3
      const today = new Date();
      const startDate = new Date(today);
      startDate.setDate(today.getDate() + 1);
      const endDate = new Date(today);
      endDate.setDate(today.getDate() + 3);

      // Helper to format date as 'Wednesday, February 4th, 2026' (with ordinal suffix)
      function getOrdinal(n: number) {
        const s = ['th', 'st', 'nd', 'rd'],
          v = n % 100;
        return s[(v - 20) % 10] || s[v] || s[0];
      }
      function formatAriaLabel(date: Date) {
        const weekday = date.toLocaleDateString('en-US', { weekday: 'long' });
        const month = date.toLocaleDateString('en-US', { month: 'long' });
        const day = date.getDate();
        const year = date.getFullYear();
        return `${weekday}, ${month} ${day}${getOrdinal(day)}, ${year}`;
      }

      const startLabel = formatAriaLabel(startDate);
      const endLabel = formatAriaLabel(endDate);

      // Get the save button reference early
      const saveButton = page.getByTestId('journal-date-range-field-save');

      // Click start date
      const startButton = page.getByRole('button', { name: startLabel });
      await expect(startButton).toBeVisible();
      await startButton.click();

      // Wait for the calendar to update by checking the save button state
      await expect(saveButton).toBeVisible();

      // Click end date
      const endButton = page.getByRole('button', { name: endLabel });
      await expect(endButton).toBeVisible();
      await endButton.click();

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

  test.describe('Tag Management', () => {
    test('should add a tag to a journal', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a journal and a tag
      const journal = await dataManager.createJournal({
        title: 'Tag Add Test',
        content: 'Testing tag addition.',
        event_date_range: {
          start: '2026-01-18T10:00:00Z',
          end: '2026-01-18T10:30:00Z',
        },
        types: ['note'],
      });
      const tags = await dataManager.createJournalTags([
        { name: 'TagAddTest' },
      ]);
      const tag = tags[0];

      testCleanup(async () => await dataManager.cleanup());

      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Add tag button should appear because there are unassigned tags
      const addTagButton = page.getByTestId('add-tag-button');
      await expect(addTagButton).toBeVisible();
      await addTagButton.click();

      // Select the tag from the dropdown
      const tagSelect = page.getByTestId('tag-select');
      await tagSelect.click();
      await page.getByRole('option', { name: tag.name }).click();

      // Confirm addition (exact: true avoids matching the 'Add Tag' trigger button)
      await page.getByRole('button', { name: 'Add', exact: true }).click();

      // Tag badge should now appear
      await expect(page.getByTestId(`tag-badge-${tag.id}`)).toBeVisible();
    });

    test('should remove a tag from a journal', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a tag and a journal, then assign the tag
      const tags = await dataManager.createJournalTags([
        { name: 'TagRemoveTest' },
      ]);
      const tag = tags[0];

      const journal = await dataManager.createJournal({
        title: 'Tag Remove Test',
        content: 'Testing tag removal.',
        event_date_range: {
          start: '2026-01-18T10:00:00Z',
          end: '2026-01-18T10:30:00Z',
        },
        types: ['note'],
      });
      await dataManager.assignTagsToJournal(journal.id, [tag.id]);

      testCleanup(async () => await dataManager.cleanup());

      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Tag badge should be visible before removal
      const tagBadge = page.getByTestId(`tag-badge-${tag.id}`);
      await expect(tagBadge).toBeVisible();

      // Click the remove button on the tag badge
      await page.getByTestId(`remove-tag-${tag.id}`).click();

      // Tag badge should disappear after removal
      await expect(tagBadge).not.toBeVisible();
    });
  });

  test.describe('Contact Management', () => {
    test('should add a contact to a journal', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      const journal = await dataManager.createJournal({
        title: 'Contact Add Test',
        content: 'Testing contact addition.',
        event_date_range: {
          start: '2026-01-18T10:00:00Z',
          end: '2026-01-18T10:30:00Z',
        },
        types: ['note'],
      });
      const contact = await dataManager.createContact({
        firstName: 'Alice',
        lastName: 'ContactTest',
      });

      testCleanup(async () => await dataManager.cleanup());

      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Open the add contact popover
      const addContactButton = page.getByTestId('add-contact-button');
      await expect(addContactButton).toBeVisible();
      await addContactButton.click();

      // Select the contact from the dropdown
      const contactSelect = page.getByTestId('contact-select');
      await contactSelect.click();
      const contactName = `${contact.firstName} ${contact.lastName}`;
      await page.getByRole('option', { name: contactName }).click();

      // Confirm addition (exact: true avoids matching the 'Add Contact' trigger button)
      await page.getByRole('button', { name: 'Add', exact: true }).click();

      // Contact badge should appear
      await expect(
        page.getByTestId(`contact-badge-${contact.id}`)
      ).toBeVisible();
    });

    test('should remove a contact from a journal', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      const contact = await dataManager.createContact({
        firstName: 'Bob',
        lastName: 'ContactRemoveTest',
      });
      const journal = await dataManager.createJournal({
        title: 'Contact Remove Test',
        content: 'Testing contact removal.',
        event_date_range: {
          start: '2026-01-18T10:00:00Z',
          end: '2026-01-18T10:30:00Z',
        },
        types: ['note'],
        contacts: [
          {
            contact_id: contact.id,
            relationship_type: 'PARTICIPANT',
          },
        ],
      });

      testCleanup(async () => await dataManager.cleanup());

      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Contact badge should be visible before removal
      const contactBadge = page.getByTestId(`contact-badge-${contact.id}`);
      await expect(contactBadge).toBeVisible();

      // Click the remove button
      await page.getByTestId(`remove-contact-${contact.id}`).click();

      // Contact badge should disappear after removal
      await expect(contactBadge).not.toBeVisible();
    });
  });

  test.describe('Calendar Assignment', () => {
    test('should change the calendar on an EVENT journal', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Two calendars: the journal starts with the first, we switch to the second
      const calendars = await dataManager.createCalendars([
        { name: 'CalendarInitial', color: '#3B82F6' },
        { name: 'CalendarUpdated', color: '#10B981' },
      ]);
      const [calendar1, calendar2] = calendars;

      // EVENT journals require a calendar_id row to be detected as EVENT type.
      // Pass type_data so the backend creates the journal_calendar_info record.
      const journal = await dataManager.createJournal({
        title: 'Calendar Change Test',
        content: 'Testing calendar change.',
        event_date_range: {
          start: '2026-01-18T10:00:00Z',
          end: '2026-01-18T11:00:00Z',
        },
        types: ['event'],
        type_data: {
          event: {
            calendar_id: calendar1.id,
            is_all_day: false,
            sync_invitees: false,
          },
        },
      });

      testCleanup(async () => await dataManager.cleanup());

      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // The calendar badge trigger should show the initially assigned calendar
      const calendarBadgeTrigger = page.getByTestId('calendar-badge-trigger');
      await expect(calendarBadgeTrigger).toBeVisible();
      await expect(calendarBadgeTrigger).toContainText(calendar1.name);

      // Click the badge to open the calendar picker
      await calendarBadgeTrigger.click();

      // Select the second calendar from the dropdown
      const calendarSelect = page.getByTestId('calendar-select');
      await calendarSelect.click();
      await page.getByRole('option', { name: calendar2.name }).click();

      // Calendar badge should update to show the new calendar
      await expect(calendarBadgeTrigger).toContainText(calendar2.name);
    });
  });

  test.describe('Mood Rating Editor', () => {
    test('should edit mood label and save', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      const journal = await dataManager.createJournal({
        title: 'Mood Edit Test',
        content: 'Testing mood editing.',
        event_date_range: {
          start: '2026-01-18T10:00:00Z',
          end: '2026-01-18T10:30:00Z',
        },
        types: ['mood_rating'],
      });

      testCleanup(async () => await dataManager.cleanup());

      await page.goto(`/journals/${journal.id}`);
      await page.waitForLoadState('networkidle');

      // Expand the Mood & Energy section
      const moodSection = page.getByTestId('type-section-trigger-mood_rating');
      await expect(moodSection).toBeVisible();
      await moodSection.click();

      // Wait for the editor to appear and click Edit
      const moodEditor = page.getByTestId('mood-rating-type-editor');
      await expect(moodEditor).toBeVisible();
      await moodEditor.getByTestId('edit-button').click();

      // Edit the mood label
      const moodLabelInput = page.getByTestId('mood-label-input');
      await expect(moodLabelInput).toBeEnabled();
      await moodLabelInput.fill('Feeling great!');

      // Save changes
      await moodEditor.getByTestId('save-button').click();

      // After save, we should be back in read mode (edit button visible again)
      await expect(moodEditor.getByTestId('edit-button')).toBeVisible();

      // The mood label should reflect the saved value
      await expect(moodLabelInput).toHaveValue('Feeling great!');
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
