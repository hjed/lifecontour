/**
 * E2E tests for contact suggestions on the Integrations page.
 *
 * Suggestions come from calendar sync recording participant emails that match
 * no contact, which an e2e test cannot drive. So the suggestion *list* is
 * route-mocked -- with a payload typed against the app's own types -- while
 * accepting, ignoring and restoring go to the real backend, and their effects
 * are checked through the real API.
 */

import type { Page, Route } from '@playwright/test';
import type {
  ContactSuggestionAcceptanceResponse,
  ContactSuggestionListResponse,
  ContactSuggestionResource,
  IgnoredContactSuggestionListResponse,
} from '../../src/types/contact-suggestions';
import { TestDataManager } from './data-management';
import { expect, test } from './fixtures';

const LIST_PATH = '/api/integrations/contact-suggestions';

function uniqueEmail(prefix: string): string {
  return `${prefix}.${crypto.randomUUID().slice(0, 8)}@e2e.test`;
}

function suggestionFor(
  email: string,
  displayName: string | null
): ContactSuggestionResource {
  return {
    type: 'contact-suggestions',
    id: email,
    attributes: {
      email,
      display_name: displayName,
      event_count: 7,
      last_seen_at: new Date().toISOString(),
    },
  };
}

/**
 * Serve `suggestions` from the list endpoint, dropping any the page has since
 * accepted or ignored for real (and restoring any it un-ignored), so the list
 * responds to the mutations the way the backend's would.
 */
async function mockSuggestionList(
  page: Page,
  suggestions: ContactSuggestionResource[]
): Promise<void> {
  const hidden = new Set<string>();

  await page.route(
    url => url.pathname.startsWith(LIST_PATH),
    async (route: Route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;

      if (path === LIST_PATH && request.method() === 'GET') {
        const body: ContactSuggestionListResponse = {
          data: suggestions.filter(s => !hidden.has(s.attributes.email)),
        };
        await route.fulfill({ json: body });
        return;
      }

      const posted = request.postDataJSON() as {
        data?: { attributes?: { email?: string } };
      } | null;
      if (request.method() === 'POST' && posted?.data?.attributes?.email) {
        hidden.add(posted.data.attributes.email);
      }
      if (request.method() === 'DELETE') {
        hidden.delete(decodeURIComponent(path.split('/').pop() ?? ''));
      }
      await route.fallback();
    }
  );
}

async function ignoredEmails(page: Page): Promise<string[]> {
  const response = await page.request.get(`${LIST_PATH}/ignored`);
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as IgnoredContactSuggestionListResponse;
  return body.data.map(entry => entry.attributes.email);
}

test.describe('Contact suggestions', () => {
  test('creates a contact from a suggestion, prefilled from the display name', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    testCleanup(() => dataManager.cleanup());
    const email = uniqueEmail('sam');
    await mockSuggestionList(page, [suggestionFor(email, 'Sam Suggested')]);

    await page.goto('/integrations');
    const row = page.getByRole('listitem', { name: email });
    await expect(row.getByText('Seen on 7 events')).toBeVisible();

    await row
      .getByRole('button', { name: `Create contact for ${email}` })
      .click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByLabel('First name')).toHaveValue('Sam');
    await expect(dialog.getByLabel('Last name')).toHaveValue('Suggested');

    const accepted = page.waitForResponse(
      response =>
        new URL(response.url()).pathname === `${LIST_PATH}/accept` &&
        response.request().method() === 'POST'
    );
    await dialog.getByRole('button', { name: 'Create contact' }).click();
    const response = await accepted;
    expect(response.status()).toBe(201);
    const body = (await response.json()) as ContactSuggestionAcceptanceResponse;
    const contactId = String(body.data.attributes.contact_id);
    dataManager.trackContact(contactId);

    await expect(dialog).toBeHidden();
    await expect(row).toBeHidden();

    const contact = await page.request.get(`/api/contacts/${contactId}`);
    expect(contact.ok()).toBe(true);
    const { attributes } = (await contact.json()).data as {
      attributes: {
        first_name: string;
        last_name: string | null;
        contact_methods: { attributes: { value: string } }[];
      };
    };
    expect(attributes.first_name).toBe('Sam');
    expect(attributes.last_name).toBe('Suggested');
    expect(attributes.contact_methods.map(m => m.attributes.value)).toEqual([
      email,
    ]);
  });

  test('ignores a suggestion persistently and restores it', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const email = uniqueEmail('noisy');
    testCleanup(async () => {
      await page.request.delete(
        `${LIST_PATH}/ignored/${encodeURIComponent(email)}`
      );
    });
    await mockSuggestionList(page, [suggestionFor(email, null)]);

    await page.goto('/integrations');
    const row = page.getByRole('listitem', { name: email });
    await expect(row).toBeVisible();

    const ignoredResponse = page.waitForResponse(
      response =>
        new URL(response.url()).pathname === `${LIST_PATH}/ignored` &&
        response.request().method() === 'POST'
    );
    await row.getByRole('button', { name: `Ignore ${email}` }).click();
    expect((await ignoredResponse).status()).toBe(201);
    await expect(row).toBeHidden();
    expect(await ignoredEmails(page)).toContain(email);

    // After a reload the Ignored list -- served by the real backend, not the
    // mock -- still holds the email.
    await page.reload();
    await expect(
      page.getByRole('heading', { name: 'Integrations', exact: true })
    ).toBeVisible();
    await expect(row).toBeHidden();
    await page.getByRole('button', { name: /^Ignored \(\d+\)$/ }).click();

    const restoredResponse = page.waitForResponse(
      response =>
        response.request().method() === 'DELETE' &&
        new URL(response.url()).pathname.startsWith(`${LIST_PATH}/ignored/`)
    );
    await page.getByRole('button', { name: `Restore ${email}` }).click();
    expect((await restoredResponse).status()).toBe(204);

    await expect(row).toBeVisible();
    expect(await ignoredEmails(page)).not.toContain(email);
  });
});
