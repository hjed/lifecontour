/**
 * E2E Tests for Contact Avatar Display
 *
 * Verifies that ContactAvatar renders correctly across
 * contact list, detail page, and journal participant views.
 *
 * Since Immich is not available in the E2E environment,
 * these tests verify the initials fallback path (photo_url=null)
 * and the correct structural presence of avatar elements.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Contact Avatars', () => {
  test('should display initials avatar on contact card in list view', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    const contact = await dataManager.createContact({
      firstName: 'AvatarList',
      lastName: 'TestUser',
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await authenticatedPage.goto('/contacts');

    // Wait for the contact card to be visible
    const contactCard = authenticatedPage.getByTestId(`contact-${contact.id}`);
    await expect(contactCard).toBeVisible({ timeout: 10000 });

    // Verify the avatar container exists within the contact card
    // ContactAvatar renders inside an Avatar wrapper with AvatarFallback showing initials
    const avatarFallback = contactCard.locator(
      '[data-testid="avatar-contact-fallback"]'
    );
    await expect(avatarFallback).toBeVisible();

    // Verify initials are rendered (first letter of first + last name)
    await expect(avatarFallback).toContainText('A');

    // No img element should be rendered since photo_url is null
    const avatarImage = contactCard.locator(
      '[data-testid="avatar-contact-image"]'
    );
    await expect(avatarImage).toHaveCount(0);
  });

  test('should display initials avatar on contact detail page', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    const contact = await dataManager.createContact({
      firstName: 'AvatarDetail',
      lastName: 'PageTest',
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Wait for the contact name to load
    await expect(
      authenticatedPage.getByText(`${contact.firstName} ${contact.lastName}`)
    ).toBeVisible({ timeout: 10000 });

    // The detail page has a large avatar (h-32 w-32)
    const avatarFallback = authenticatedPage
      .locator('[data-testid="avatar-contact-fallback"]')
      .first();
    await expect(avatarFallback).toBeVisible();

    // Verify initials are rendered
    await expect(avatarFallback).toContainText('A');
  });

  test('should display initials avatar on journal participant badges', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Create a contact
    const contact = await dataManager.createContact({
      firstName: 'JournalAvatar',
      lastName: 'Participant',
    });

    // Create a calendar for the journal
    const calendars = await dataManager.createCalendars([
      { name: 'AvatarTestCal', color: '#3b82f6' },
    ]);
    const calendarId = calendars[0]!.id;

    // Create a journal with this contact as participant
    const today = new Date().toISOString();
    const journal = await dataManager.createJournal({
      title: 'Avatar Test Journal',
      content: 'Testing avatar display on journal participants',
      event_date_range: { start: today, end: today },
      types: ['event'],
      type_data: {
        event: {
          calendar_id: calendarId,
          is_all_day: false,
        },
      },
      contacts: [
        {
          contact_id: contact.id,
          relationship_type: 'PARTICIPANT',
        },
      ],
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Navigate to the journal detail page
    await authenticatedPage.goto(`/journals/${journal.id}`);

    // Wait for the journal to load using the title heading (not breadcrumb)
    await expect(
      authenticatedPage.getByTestId('journal-title-field')
    ).toBeVisible({ timeout: 10000 });

    // Verify participant contact badge has an avatar
    const contactBadge = authenticatedPage.getByTestId(
      `contact-badge-${contact.id}`
    );
    await expect(contactBadge).toBeVisible({ timeout: 10000 });

    // The badge should contain an avatar with initials fallback
    const avatarInBadge = contactBadge.locator(
      '[data-testid="avatar-contact-fallback"]'
    );
    await expect(avatarInBadge).toBeVisible();
  });
});
