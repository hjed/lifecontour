/**
 * E2E Tests for External System Links Display
 *
 * Tests that ExternalLinksDisplay renders correctly on journal and contact
 * detail pages. Uses API route interception for external-links endpoints
 * since external system data (Strava, Google Calendar, etc.) is populated
 * by integration workers rather than through the UI.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('External Links Display', () => {
  test.describe('Journal Detail Page', () => {
    test('should display Strava external link on journal detail', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);
      await dataManager.clearAllJournals();

      const journals = await dataManager.createJournals([
        {
          title: 'Morning Run',
          content: 'A test journal with Strava link.',
          event_date_range: {
            start: new Date().toISOString(),
            end: new Date().toISOString(),
          },
        },
      ]);
      const journal = journals[0];

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Mock the external-links endpoint to return a Strava link
      await page.route(
        `**/api/journals/${journal.id}/external-links`,
        async route => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              data: [
                {
                  type: 'external_links',
                  id: 'strava-12345678',
                  attributes: {
                    source: 'strava',
                    url: 'https://www.strava.com/activities/12345678',
                    external_id: '12345678',
                  },
                },
              ],
            }),
          });
        }
      );

      await page.goto(`/journals/${journal.id}`);
      await expect(page.getByTestId('journal-title-field')).toBeVisible();

      // Verify the external links section renders
      const section = page.getByTestId('external-links-section');
      await expect(section).toBeVisible();
      await expect(section).toContainText('Linked Systems');

      // Verify the Strava badge renders with correct link
      const stravaLink = page.getByTestId('external-link-strava');
      await expect(stravaLink).toBeVisible();
      await expect(stravaLink).toContainText('Strava');
      await expect(stravaLink).toHaveAttribute(
        'href',
        'https://www.strava.com/activities/12345678'
      );
      await expect(stravaLink).toHaveAttribute('target', '_blank');
      await expect(stravaLink).toHaveAttribute('rel', 'noopener noreferrer');

      // Verify accessibility: aria-label
      await expect(stravaLink).toHaveAttribute('aria-label', 'Open in Strava');
    });

    test('should display multiple external links on journal detail', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);
      await dataManager.clearAllJournals();

      const journals = await dataManager.createJournals([
        {
          title: 'Multi-linked Journal',
          content: 'Journal with multiple external links.',
          event_date_range: {
            start: new Date().toISOString(),
            end: new Date().toISOString(),
          },
        },
      ]);
      const journal = journals[0];

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Mock with both Strava and Google Calendar links
      await page.route(
        `**/api/journals/${journal.id}/external-links`,
        async route => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              data: [
                {
                  type: 'external_links',
                  id: 'strava-99999',
                  attributes: {
                    source: 'strava',
                    url: 'https://www.strava.com/activities/99999',
                    external_id: '99999',
                  },
                },
                {
                  type: 'external_links',
                  id: 'google_calendar-google-event-abc',
                  attributes: {
                    source: 'google_calendar',
                    url: 'https://calendar.google.com/calendar/event?eid=abc123',
                    external_id: 'google-event-abc',
                  },
                },
              ],
            }),
          });
        }
      );

      await page.goto(`/journals/${journal.id}`);
      await expect(page.getByTestId('journal-title-field')).toBeVisible();

      const section = page.getByTestId('external-links-section');
      await expect(section).toBeVisible();

      // Both badges should be visible
      await expect(page.getByTestId('external-link-strava')).toBeVisible();
      await expect(
        page.getByTestId('external-link-google_calendar')
      ).toBeVisible();
      await expect(
        page.getByTestId('external-link-google_calendar')
      ).toContainText('Google Calendar');
    });

    test('should not display external links section when no links exist', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);
      await dataManager.clearAllJournals();

      const journals = await dataManager.createJournals([
        {
          title: 'Plain Journal',
          content: 'A journal with no external links.',
          event_date_range: {
            start: new Date().toISOString(),
            end: new Date().toISOString(),
          },
        },
      ]);
      const journal = journals[0];

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Mock with empty links
      await page.route(
        `**/api/journals/${journal.id}/external-links`,
        async route => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ data: [] }),
          });
        }
      );

      await page.goto(`/journals/${journal.id}`);
      await expect(page.getByTestId('journal-title-field')).toBeVisible();

      // Section should not exist when there are no links
      await expect(page.getByTestId('external-links-section')).toBeHidden();
    });
  });

  test.describe('Contact Detail Page', () => {
    test('should display Google Contacts external link on contact detail', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      const contacts = await dataManager.createContacts([
        {
          firstName: 'ExtLink',
          lastName: 'TestContact',
          email: 'extlink@example.com',
        },
      ]);
      const contact = contacts[0];

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Mock the external-links endpoint to return a Google Contacts link
      await page.route(
        `**/api/contacts/${contact.id}/external-links`,
        async route => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              data: [
                {
                  type: 'external_links',
                  id: 'google_contacts-people/c123456',
                  attributes: {
                    source: 'google_contacts',
                    url: 'https://contacts.google.com/person/c123456',
                    external_id: 'people/c123456',
                  },
                },
              ],
            }),
          });
        }
      );

      await page.goto(`/contacts/${contact.id}`);

      // Wait for the contact page to load
      await expect(
        page.getByRole('region', { name: 'Contact Detail' })
      ).toBeVisible({
        timeout: 15000,
      });

      // Verify the external links section renders
      const section = page.getByTestId('external-links-section');
      await expect(section).toBeVisible();
      await expect(section).toContainText('Linked Systems');

      // Verify the Google Contacts badge
      const googleLink = page.getByTestId('external-link-google_contacts');
      await expect(googleLink).toBeVisible();
      await expect(googleLink).toContainText('Google Contacts');
      await expect(googleLink).toHaveAttribute(
        'href',
        'https://contacts.google.com/person/c123456'
      );
      await expect(googleLink).toHaveAttribute('target', '_blank');

      // Verify accessibility
      await expect(googleLink).toHaveAttribute(
        'aria-label',
        'Open in Google Contacts'
      );
    });

    test('should not display external links section on contact with no links', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      const contacts = await dataManager.createContacts([
        {
          firstName: 'NoLink',
          lastName: 'TestContact',
          email: 'nolink@example.com',
        },
      ]);
      const contact = contacts[0];

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      // Mock with empty links
      await page.route(
        `**/api/contacts/${contact.id}/external-links`,
        async route => {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ data: [] }),
          });
        }
      );

      await page.goto(`/contacts/${contact.id}`);

      // Wait for the contact page to load
      await expect(
        page.getByRole('region', { name: 'Contact Detail' })
      ).toBeVisible({
        timeout: 15000,
      });

      // Section should not exist
      await expect(page.getByTestId('external-links-section')).toBeHidden();
    });
  });
});
