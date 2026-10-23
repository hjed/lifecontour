/**
 * E2E tests for the flag on addresses a Google import skipped (#1820).
 *
 * The e2e stack has no Google to skip an address, so the issue is recorded
 * through the test-only create (`ENABLE_TEST_IMPORT_ISSUES`). The wording and
 * hiding rules are unit-tested; this covers the contact page, the
 * Integrations list and dismissing against the real API.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Skipped import addresses', () => {
  test('flags a skipped address on the contact and the Integrations page, then dismisses it', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const data = new TestDataManager(page);
    testCleanup(async () => {
      await data.cleanup();
    });
    const contact = await data.createContact({
      firstName: 'Kiri',
      lastName: 'Skipped',
    });
    const street = `10 Downing St ${crypto.randomUUID().slice(0, 8)}`;
    const created = await page.request.post('/api/integrations/import-issues', {
      data: {
        data: {
          type: 'contact-import-issues',
          attributes: {
            contact_id: Number(contact.id),
            address: {
              street_line_1: street,
              region: 'London',
              country_code: 'AU',
            },
          },
        },
      },
    });
    expect(created.status()).toBe(201);

    await page.goto('/integrations');
    const card = page.getByTestId('skipped-addresses');
    await expect(card.getByText(street, { exact: false })).toBeVisible();
    await expect(
      card.getByRole('link', {
        name: `${contact.firstName} ${contact.lastName}`,
      })
    ).toHaveAttribute('href', `/contacts/${contact.id}`);

    await page.goto(`/contacts/${contact.id}`);
    const flag = page.getByTestId('contact-import-issues');
    await expect(flag).toContainText('A Google address wasn’t imported');
    await expect(flag).toContainText(
      '“London” isn’t a state or territory of Australia'
    );

    const dismissed = page.waitForResponse(
      res =>
        res.url().includes('/api/integrations/import-issues/') &&
        res.url().endsWith('/dismiss') &&
        res.request().method() === 'POST'
    );
    await flag.getByRole('button', { name: 'Dismiss' }).click();
    expect((await dismissed).status()).toBe(204);
    await expect(flag).toBeHidden();
  });
});
