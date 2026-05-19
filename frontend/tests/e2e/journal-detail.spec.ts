/**
 * E2E Tests for Journal Detail Page
 *
 * Tests the integration of JournalDetailView and all Phase 4 components
 * in the /journals/[id] page.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import { waitForContactSearchIndexing } from './utils/test-helpers';

// Helper to get ordinal suffix for a day number (e.g., 1 -> 'st')
function getOrdinal(n: number) {
  const s = ['th', 'st', 'nd', 'rd'],
    v = n % 100;
  return s[(v - 20) % 10] || s[v] || s[0];
}

// Helper to format date as 'Wednesday, February 4th, 2026' (with ordinal suffix)
function formatAriaLabel(date: Date) {
  const weekday = date.toLocaleDateString('en-US', { weekday: 'long' });
  const month = date.toLocaleDateString('en-US', { month: 'long' });
  const day = date.getDate();
  const year = date.getFullYear();
  return `${weekday}, ${month} ${day}${getOrdinal(day)}, ${year}`;
}

test.describe('Journal Detail Page', () => {
  test.describe('Basic Display', () => {
    test('should display journal details', async ({ journalsWithData }) => {
      const { page, journals } = journalsWithData;
      const journal = journals[0];

      // Navigate to journal detail page
      await page.goto(`/journals/${journal.id}`);

      // Wait for page to load - use element-based wait instead of networkidle
      await expect(page.getByTestId('journal-title-field')).toBeVisible();

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
      await expect(
        page.getByRole('alert').filter({ hasText: /failed to load journal/i })
      ).toBeVisible({ timeout: 15000 });

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
      await expect(page.getByTestId('journal-title-field')).toBeVisible();

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
      await expect(page.getByTestId('journal-content')).toBeVisible();

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
      await expect(page.getByTestId('journal-date-range-field')).toBeVisible();

      // Find the date range field (it's a button in view mode)
      const dateField = page.getByTestId('journal-date-range-field');
      await expect(dateField).toBeVisible();

      // Get the original date range text
      const originalDateRange = await dateField.textContent();

      // Click to enter edit mode (this automatically opens the calendar)
      await dateField.click();

      // Wait for the calendar to appear using web-first assertion (auto-retry)
      // instead of legacy waitForSelector which doesn't retry
      const calendarGrid = page.locator('[role="grid"]').first();
      await expect(calendarGrid).toBeVisible();

      // Dynamically pick two dates: today + 1 and today + 3
      const today = new Date();
      const startDate = new Date(today);
      startDate.setDate(today.getDate() + 1);
      const endDate = new Date(today);
      endDate.setDate(today.getDate() + 3);

      const startLabel = formatAriaLabel(startDate);
      const endLabel = formatAriaLabel(endDate);

      // Get the month name for each date to scope clicks to the correct
      // calendar grid.  Dates at month boundaries can appear as overflow
      // days in an adjacent month's grid, causing strict-mode violations.
      const startMonth = startDate.toLocaleDateString('en-US', {
        month: 'long',
      });
      const endMonth = endDate.toLocaleDateString('en-US', { month: 'long' });

      // Get the save button reference early
      const saveButton = page.getByTestId('journal-date-range-field-save');

      // Click start date – scoped to its month grid
      const startGrid = page.getByRole('grid', { name: startMonth });
      const startButton = startGrid.getByRole('button', { name: startLabel });
      await expect(startButton).toBeVisible();
      await startButton.click();

      // Wait for the calendar to update by checking the save button state
      await expect(saveButton).toBeVisible();

      // Click end date – scoped to its month grid
      const endGrid = page.getByRole('grid', { name: endMonth });
      const endButton = endGrid.getByRole('button', { name: endLabel });
      await expect(endButton).toBeVisible();
      await endButton.click();

      // Wait for the save button to be enabled (both dates selected)
      await expect(saveButton).toBeVisible();
      await expect(saveButton).toBeEnabled();

      // Save the changes
      await saveButton.click();

      // Wait for the edit mode to close
      await expect(saveButton).toBeHidden();

      // Verify the date range was updated (should be different from original)
      await expect(dateField).not.toHaveText(originalDateRange || '');
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
        await expect(page.locator('main, [role="main"]').first()).toBeVisible();

        // Verify type badges are displayed
        for (const type of journal.types || []) {
          await expect(page.getByTestId(`manage-type-${type}`)).toBeVisible();
        }
      }
    });

    test('should display type-specific editor sections for EVENT type', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(authenticatedPage);
      // Register cleanup
      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Create a calendar so the journal will properly be recognized as an EVENT
      const calendars = await dataManager.createCalendars([
        { name: 'Test Calendar', color: '#10b981' },
      ]);
      const calendar = calendars[0];

      const today = new Date();
      const journals = await dataManager.createJournals([
        {
          title: 'Event Journal',
          content: 'Event Journal Content',
          types: ['event'],
          event_date_range: {
            start: today.toISOString(),
            end: today.toISOString(),
          },
          type_data: {
            event: {
              calendar_id: calendar.id,
              is_all_day: true,
            },
          },
        },
      ]);
      const journalData = journals[0];

      const page = authenticatedPage;

      // Navigate to journal detail page
      await page.goto(`/journals/${journalData.id}`);
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Wait for the journal to load and display UI
      await expect(page.getByTestId('journal-detail-view')).toBeVisible();

      // Verify EVENT type section is present
      const eventSection = page.getByText('Event Details');
      await expect(eventSection).toBeVisible();

      // Click to expand the section if it's collapsed
      await eventSection.click();

      // Verify event-specific fields are visible
      // These should be in the EventTypeEditor component
      await expect(page.getByText(/calendar/i).first()).toBeVisible();
    });

    test('should allow editing EVENT type data', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(authenticatedPage);
      testCleanup(async () => {
        await dataManager.cleanup();
      });

      const calendars = await dataManager.createCalendars([
        { name: 'Edit Event Test Calendar', color: '#8b5cf6' },
      ]);
      const calendar = calendars[0];

      const today = new Date();
      const journals = await dataManager.createJournals([
        {
          title: 'Event Journal Edit',
          content: 'Event Journal Edit Content',
          types: ['event'],
          event_date_range: {
            start: today.toISOString(),
            end: today.toISOString(),
          },
          type_data: {
            event: {
              calendar_id: calendar.id,
              is_all_day: false,
            },
          },
        },
      ]);
      const journalData = journals[0];

      const page = authenticatedPage;

      // Navigate to journal detail page
      await page.goto(`/journals/${journalData.id}`);
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Wait for the journal to load and display UI
      await expect(page.getByTestId('journal-detail-view')).toBeVisible();

      // Find and expand the Event Details section
      const eventSection = page.getByText('Event Details');
      await expect(eventSection).toBeVisible();
      await eventSection.click();

      // Wait for the Event Type Editor to be visible
      const eventTypeEditor = page.getByTestId('event-type-editor');
      await expect(eventTypeEditor).toBeVisible();

      // Click the edit button specifically for the event editor
      const editButton = eventTypeEditor.getByTestId('edit-button');
      await expect(editButton).toBeVisible();
      await editButton.click();

      // Verify we're in edit mode using the scoped event editor controls
      const saveButton = eventTypeEditor.getByTestId('save-button');
      const cancelButton = eventTypeEditor.getByTestId('cancel-button');

      await expect(saveButton).toBeVisible();
      await expect(cancelButton).toBeVisible();

      // Actually change a field, let's say Location
      const locationInput = eventTypeEditor.getByTestId('location-input');
      await locationInput.fill('New Prod Location');

      // Change time fields to verify backend accepts valid time inputs
      const startTimeInput = eventTypeEditor.getByTestId('start-time-input');
      await startTimeInput.fill('12:30');

      const endTimeInput = eventTypeEditor.getByTestId('end-time-input');
      await endTimeInput.fill('13:30');

      const [response] = await Promise.all([
        page.waitForResponse(response => {
          return (
            response.url().includes('/api/journals/') &&
            response.request().method() === 'PUT'
          );
        }),
        saveButton.click(),
      ]);

      const updateStatus = response.status();
      const responseText = await response.text();
      expect(
        updateStatus,
        `Expected 200 but got ${updateStatus}. Response: ${responseText}`
      ).toBe(200);

      // Wait for edit mode to finish
      await expect(saveButton).toBeHidden();
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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

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

    test('should display type-specific editor sections for FITNESS type', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;

      // Create a journal with FITNESS type
      const response = await page.request.post('/api/journals', {
        data: {
          data: {
            type: 'journal',
            attributes: {
              title: 'Morning Run',
              content: 'Ran to the park and back.',
              event_date_range: {
                start: '2026-01-18T10:00:00Z',
                end: '2026-01-18T10:30:00Z',
              },
              types: ['fitness'],
              type_data: {
                fitness: {
                  duration: 1800,
                  distance: 5000,
                  heart_rate_avg: 155,
                },
              },
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
      // Wait for the page title to be visible rather than network-idle, as Leaflet tile
      // loading can keep the network busy and cause flaky timeouts.
      await expect(page.getByTestId('journal-title-field')).toBeVisible();

      // Verify FITNESS type section is present
      const fitnessSection = page.getByText('Fitness Activity');
      await expect(fitnessSection).toBeVisible();

      // Click the collapsible trigger to expand the section
      await page.getByTestId('type-section-trigger-fitness').click();

      // Verify fitness-specific stats are visible
      await expect(page.getByTestId('activity-stats-grid')).toBeVisible();
      await expect(page.getByTestId('stat-distance')).toHaveText('5.00 km');
      await expect(page.getByTestId('stat-duration')).toHaveText('30:00');

      // Expand to edit mode and confirm form input populates correctly
      const fitnessEditor = page.getByTestId('fitness-type-editor');
      const editButton = fitnessEditor.getByTestId('edit-button');
      await expect(editButton).toBeVisible();
      await editButton.click();

      const distanceInput = page.getByTestId('distance-input');
      await expect(distanceInput).toBeVisible();
      await expect(distanceInput).toHaveValue('5000');
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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Add tag button should appear because there are unassigned tags
      const addTagButton = page.getByTestId('add-tag-button');
      await expect(addTagButton).toBeVisible();
      await addTagButton.click();

      // Select the tag from the dropdown
      const tagSelect = page.getByTestId('tag-select');
      await tagSelect.click();
      await page.getByRole('option', { name: tag.name }).click();

      // Confirm addition — wait for the API response so the UI has time to update
      await Promise.all([
        page.waitForResponse(
          resp =>
            resp.url().includes(`/api/journals/${journal.id}`) &&
            resp.request().method() === 'POST'
        ),
        page.getByRole('button', { name: 'Add', exact: true }).click(),
      ]);

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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Tag badge should be visible before removal
      const tagBadge = page.getByTestId(`tag-badge-${tag.id}`);
      await expect(tagBadge).toBeVisible();

      // Click the remove button on the tag badge
      const removeButton = page.getByTestId(`remove-tag-${tag.id}`);
      await expect(removeButton).toBeVisible();
      await removeButton.click();

      // Tag badge should disappear after removal
      await expect(tagBadge).toBeHidden();
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

      // Wait for MeiliSearch to index the contact before searching
      await waitForContactSearchIndexing(
        page,
        contact.firstName,
        `${contact.firstName} ${contact.lastName}`
      );

      await page.goto(`/journals/${journal.id}`);
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();
      await expect(page.getByTestId('journal-detail-view')).toBeVisible();

      // Open the add contact popover
      const addContactButton = page.getByTestId('add-contact-button');
      await expect(addContactButton).toBeVisible();
      await addContactButton.click();

      const contactName = `${contact.firstName} ${contact.lastName}`;
      const contactSearchCombobox = page.getByPlaceholder(
        'Search for a contact...'
      );
      await expect(contactSearchCombobox).toBeVisible();
      await contactSearchCombobox.fill(contact.firstName);
      await expect(page.getByRole('listbox')).toBeVisible();
      await page.getByRole('option', { name: contactName }).click();
      await expect(
        page.getByText(contactName, { exact: true }).first()
      ).toBeVisible();

      // Wait for the POST update request and the subsequent GET refetch
      const [addResponse] = await Promise.all([
        page.waitForResponse(
          resp =>
            resp.url().includes(`/api/journals/${journal.id}`) &&
            resp.request().method() === 'POST'
        ),
        page.waitForResponse(
          resp =>
            resp.url().endsWith(`/api/journals/${journal.id}`) &&
            resp.request().method() === 'GET'
        ),
        page.getByRole('button', { name: 'Add', exact: true }).click(),
      ]);
      expect(addResponse.status()).toBe(200);

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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();
      await expect(page.getByTestId('journal-detail-view')).toBeVisible();

      // Contact badge should be visible before removal
      const contactBadge = page.getByTestId(`contact-badge-${contact.id}`);
      await expect(contactBadge).toBeVisible();

      // Click the remove button
      const removeContactButton = page.getByTestId(
        `remove-contact-${contact.id}`
      );
      await expect(removeContactButton).toBeVisible();

      // Ensure the button is in view before attempting the click sequence
      await removeContactButton.scrollIntoViewIfNeeded();

      // Wait for the API call to complete and the subsequent GET refetch
      const [removeResponse] = await Promise.all([
        page.waitForResponse(
          resp =>
            resp.url().includes(`/api/journals/${journal.id}`) &&
            resp.request().method() === 'DELETE'
        ),
        page.waitForResponse(
          resp =>
            resp.url().endsWith(`/api/journals/${journal.id}`) &&
            resp.request().method() === 'GET'
        ),
        removeContactButton.click(),
      ]);
      expect(removeResponse.status()).toBe(200);

      // Contact badge should disappear after removal
      await expect(contactBadge).toBeHidden();
    });

    test('should edit a contact status and role in a journal', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      const contact = await dataManager.createContact({
        firstName: 'Charlie',
        lastName: 'ContactEditTest',
      });
      const journal = await dataManager.createJournal({
        title: 'Contact Edit Test',
        content: 'Testing contact editing.',
        event_date_range: {
          start: '2026-01-18T10:00:00Z',
          end: '2026-01-18T10:30:00Z',
        },
        types: ['note'],
        contacts: [
          {
            contact_id: contact.id,
            relationship_type: 'PARTICIPANT',
            status: 'NO_REPLY',
          },
        ],
      });

      testCleanup(async () => await dataManager.cleanup());

      await page.goto(`/journals/${journal.id}`);
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();
      await expect(page.getByTestId('journal-detail-view')).toBeVisible();

      // Contact badge should be visible
      const contactBadge = page.getByTestId(`contact-badge-${contact.id}`);
      await expect(contactBadge).toBeVisible();

      // Verify initial status
      const neutralStatus = page.getByTestId(`contact-status-${contact.id}`);
      await expect(neutralStatus).toBeVisible();

      // Click the edit button (z-10 ensures it's above the link hit area)
      const editButton = page.getByTestId(`edit-contact-${contact.id}`);
      await editButton.click();

      // Ensure popover appears
      const popoverContent = page.locator('[role="dialog"]');
      await expect(popoverContent).toBeVisible();

      // Change Status to ATTENDING
      const statusSelect = popoverContent
        .locator('button[role="combobox"]')
        .first();
      await statusSelect.click();
      await page.getByRole('option', { name: 'ATTENDING' }).click();

      // Change Role to ORGANISER
      const roleSelect = popoverContent
        .locator('button[role="combobox"]')
        .nth(1);
      await roleSelect.click();
      await page.getByRole('option', { name: 'ORGANISER' }).click();

      // Wait for both the PATCH API call and the React Query invalidation refetch to complete
      const [updateResponse] = await Promise.all([
        page.waitForResponse(
          resp =>
            resp.url().includes(`/relationships/contacts/${contact.id}`) &&
            resp.request().method() === 'PATCH'
        ),
        // Wait for the React Query invalidation refetch to complete before
        // asserting UI state — Firefox re-renders can lag behind the PATCH response.
        page.waitForResponse(
          resp =>
            resp.url().includes(`/api/journals/${journal.id}`) &&
            resp.request().method() === 'GET' &&
            resp.status() === 200
        ),
        page.getByRole('button', { name: 'Save' }).click(),
      ]);
      expect(updateResponse.status()).toBe(200);

      // Verify the UI updated to new status
      await expect(popoverContent).toBeHidden();

      const updatedStatus = page.getByTestId(`contact-status-${contact.id}`);
      await expect(updatedStatus).toHaveAttribute(
        'aria-label',
        'Status: ATTENDING',
        { timeout: 15000 }
      );

      const roleBadge = page.getByTestId(`contact-role-${contact.id}`);
      await expect(roleBadge).toBeVisible();
      await expect(roleBadge).toContainText('ORG');
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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

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

  test.describe('Event State', () => {
    test('should default event_state to confirmed on event journal creation', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      const calendars = await dataManager.createCalendars([
        { name: 'EventStateTest', color: '#3B82F6' },
      ]);
      const calendar = calendars[0];

      const journal = await dataManager.createJournal({
        title: 'Event State Default Test',
        content: 'Testing event_state defaults to confirmed.',
        event_date_range: {
          start: '2026-03-20T10:00:00Z',
          end: '2026-03-20T11:00:00Z',
        },
        types: ['event'],
        type_data: {
          event: {
            calendar_id: calendar.id,
            is_all_day: false,
            sync_invitees: false,
          },
        },
      });

      testCleanup(async () => await dataManager.cleanup());

      // Fetch the journal via API and verify event_state
      const response = await page.request.get(`/api/journals/${journal.id}`);
      expect(response.ok()).toBe(true);

      const responseData = await response.json();
      const typeData = responseData.data.attributes.type_data;

      expect(typeData).toBeDefined();
      expect(typeData.event).toBeDefined();
      expect(typeData.event.event_state).toBe('confirmed');
    });

    test('should return event_state in API response for event journal detail page', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      const calendars = await dataManager.createCalendars([
        { name: 'EventStateAPITest', color: '#10B981' },
      ]);
      const calendar = calendars[0];

      const journal = await dataManager.createJournal({
        title: 'Event State API Test',
        content: 'Verifying event_state in API response.',
        event_date_range: {
          start: '2026-03-20T14:00:00Z',
          end: '2026-03-20T15:00:00Z',
        },
        types: ['event'],
        type_data: {
          event: {
            calendar_id: calendar.id,
            is_all_day: false,
            sync_invitees: false,
            start_time: '14:00:00',
            end_time: '15:00:00',
            location: 'Test Location',
          },
        },
      });

      testCleanup(async () => await dataManager.cleanup());

      // Navigate to the detail page via browser (full stack E2E)
      await page.goto(`/journals/${journal.id}`);
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Verify the journal loaded successfully
      await expect(page.getByTestId('journal-title-field')).toContainText(
        journal.title
      );

      // Intercept the API call made by the page to check type_data
      const apiResponse = await page.request.get(`/api/journals/${journal.id}`);
      const apiData = await apiResponse.json();

      // Verify event_state is present and defaults to confirmed
      const eventData = apiData.data.attributes.type_data?.event;
      expect(eventData).toBeDefined();
      expect(eventData.event_state).toBe('confirmed');
      expect(eventData.calendar_id).toBe(calendar.id);
      expect(eventData.location).toBe('Test Location');
    });

    test('should persist event_state through journal update', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      const calendars = await dataManager.createCalendars([
        { name: 'EventStateUpdateTest', color: '#F59E0B' },
      ]);
      const calendar = calendars[0];

      const journal = await dataManager.createJournal({
        title: 'Event State Update Test',
        content: 'Testing event_state persists through updates.',
        event_date_range: {
          start: '2026-03-20T09:00:00Z',
          end: '2026-03-20T10:00:00Z',
        },
        types: ['event'],
        type_data: {
          event: {
            calendar_id: calendar.id,
            is_all_day: false,
            sync_invitees: false,
          },
        },
      });

      testCleanup(async () => await dataManager.cleanup());

      // Update the journal title via API
      const updateResponse = await page.request.patch(
        `/api/journals/${journal.id}`,
        {
          data: {
            data: {
              type: 'journals',
              id: journal.id,
              attributes: {
                title: 'Updated Event State Test',
              },
            },
          },
        }
      );
      expect(updateResponse.ok()).toBe(true);

      // Verify event_state is still confirmed after update
      const getResponse = await page.request.get(`/api/journals/${journal.id}`);
      const getData = await getResponse.json();
      const eventData = getData.data.attributes.type_data?.event;

      expect(eventData).toBeDefined();
      expect(eventData.event_state).toBe('confirmed');
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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

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
      await expect(page.locator('main, [role="main"]').first()).toBeVisible();

      // Find and click the back button - use button role instead of link
      const backButton = page.getByRole('button', { name: /back/i });

      // Only run test if back button is visible
      await expect(backButton).toBeVisible();
      await backButton.click();

      // Wait for navigation to complete
      await page.waitForURL('**/journals');

      // Verify we're on the list page
      expect(page.url()).toContain('/journals');
      expect(page.url()).not.toContain(`/journals/${journal.id}`);
    });

    test('should navigate to contact detail page when contact badge is clicked', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      // Create a journal and a contact
      const contact = await dataManager.createContact({
        firstName: 'Click',
        lastName: 'NavigationTest',
      });
      const journal = await dataManager.createJournal({
        title: 'Badge Navigation Test',
        content: 'Testing badge link navigation.',
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
      await expect(page.getByTestId('journal-detail-view')).toBeVisible();

      // Wait for the contact badge to render before looking for the link
      await expect(
        page.getByTestId(`contact-badge-${contact.id}`)
      ).toBeVisible();

      // Click the link inside the contact badge
      const contactLink = page.getByRole('link', {
        name: `View ${contact.firstName} ${contact.lastName}`,
      });
      await expect(contactLink).toBeVisible();

      await contactLink.click();

      // Wait for navigation and verify url
      await page.waitForURL(`**/contacts/${contact.id}**`);
      expect(page.url()).toContain(`/contacts/${contact.id}`);
    });
  });
});
