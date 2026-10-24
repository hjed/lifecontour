import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';

/**
 * Conditional writes on the contact page (#1812): inline edits send the
 * contact's ETag as If-Match, so an edit made against a stale copy is refused
 * (412) and the conflict dialog offers to re-apply it.
 *
 * The serialisation of quick edits and the dialog's wording are unit-tested
 * (contact-conditional-writes.test.ts, write-conflicts.test.tsx,
 * WriteConflictDialog.test.tsx); these cover the real round trip through the
 * backend's tags.
 */

function fieldPatch(contactId: string, fieldName: string) {
  return (res: { url(): string; request(): { method(): string } }) =>
    res.url().includes(`/api/contacts/${contactId}/fields/${fieldName}`) &&
    res.request().method() === 'PATCH';
}

async function editInline(page: Page, testId: string, value: string) {
  const field = page.getByTestId(testId);
  await expect(field).toBeVisible();
  await field.click();
  const input = field.locator('input');
  await expect(input).toBeVisible();
  await input.clear();
  await input.fill(value);
  await input.press('Enter');
}

test.describe('Contact write conflicts', () => {
  test('an edit against a stale copy is refused, and Keep mine re-applies it', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);
    await expect(page.getByTestId('nickname-field')).toBeVisible();

    // Another tab renames the contact after this page read it.
    const elsewhere = await page.request.patch(
      `/api/contacts/${contact.id}/fields/first_name`,
      {
        data: {
          data: {
            type: 'contact_fields',
            attributes: { value: 'ChangedElsewhere' },
          },
        },
      }
    );
    expect(elsewhere.status()).toBe(200);

    const refused = page.waitForResponse(fieldPatch(contact.id, 'nick_name'));
    await editInline(page, 'nickname-field', 'MyNickname');
    expect((await refused).status()).toBe(412);

    const dialog = page.getByTestId('write-conflict-dialog');
    await expect(dialog).toBeVisible();
    await expect(page.getByTestId('write-conflict-changed')).toHaveText(
      'Changed: First name.'
    );
    await expect(page.getByTestId('write-conflict-attempted')).toHaveText(
      'Your change: Nickname → MyNickname'
    );
    // The page already shows the other tab's version.
    await expect(page.getByTestId('first-name-field')).toContainText(
      'ChangedElsewhere'
    );

    const reapplied = page.waitForResponse(fieldPatch(contact.id, 'nick_name'));
    await dialog.getByRole('button', { name: 'Keep mine' }).click();
    expect((await reapplied).status()).toBe(200);
    await expect(dialog).toBeHidden();
    // The field closed when the edit was refused, and shows the re-applied value.
    await expect(
      page.getByTestId('nickname-field').locator('input')
    ).toHaveCount(0);
    await expect(page.getByTestId('nickname-field')).toContainText(
      'MyNickname'
    );

    // Both changes persisted.
    await page.reload();
    await expect(page.getByTestId('first-name-field')).toContainText(
      'ChangedElsewhere'
    );
    await expect(page.getByTestId('nickname-field')).toContainText(
      'MyNickname'
    );
  });

  test('a second edit made while the first is in flight is not refused', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    await page.goto(`/contacts/${contact.id}`);
    await expect(page.getByTestId('first-name-field')).toBeVisible();

    // Hold the first edit at the network, so the second is made before the
    // first's new tag is known; it must wait for it rather than race it.
    let release!: () => void;
    const held = new Promise<void>(resolve => {
      release = resolve;
    });
    await page.route(
      `**/api/contacts/${contact.id}/fields/first_name`,
      async route => {
        await held;
        await route.continue();
      }
    );

    const first = page.waitForResponse(fieldPatch(contact.id, 'first_name'));
    const second = page.waitForResponse(fieldPatch(contact.id, 'nick_name'));
    await editInline(page, 'first-name-field', 'QuickFirst');
    await editInline(page, 'nickname-field', 'QuickNick');
    release();

    expect((await first).status()).toBe(200);
    expect((await second).status()).toBe(200);
    await expect(page.getByTestId('write-conflict-dialog')).toHaveCount(0);

    await page.reload();
    await expect(page.getByTestId('first-name-field')).toContainText(
      'QuickFirst'
    );
    await expect(page.getByTestId('nickname-field')).toContainText('QuickNick');
  });

  test('an edit to one of the contact rows conflicts with a change elsewhere in the contact', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];
    const seeded = await page.request.post(
      `/api/contacts/${contact.id}/methods`,
      {
        data: {
          data: {
            type: 'contact_methods',
            attributes: {
              method_type: 'email',
              value: 'john.doe@example.com',
              is_primary: true,
            },
          },
        },
      }
    );
    expect(seeded.ok()).toBe(true);

    await page.goto(`/contacts/${contact.id}`);
    const email = page.getByRole('button', { name: /^Email address/ }).first();
    await expect(email).toContainText('john.doe@example.com');

    // Another tab changes a different part of the contact.
    const elsewhere = await page.request.patch(
      `/api/contacts/${contact.id}/fields/nick_name`,
      {
        data: {
          data: {
            type: 'contact_fields',
            attributes: { value: 'Elsewhere' },
          },
        },
      }
    );
    expect(elsewhere.status()).toBe(200);

    const isEmailEdit = (res: {
      url(): string;
      request(): { method(): string };
    }) =>
      /\/api\/contacts\/[^/]+\/methods\/[^/]+\/fields\/value$/.test(
        res.url()
      ) && res.request().method() === 'PATCH';
    const refused = page.waitForResponse(isEmailEdit);
    await email.click();
    const input = page.getByRole('textbox', { name: /^Email address/ });
    await input.clear();
    await input.fill('john.new@example.com');
    await input.press('Enter');
    expect((await refused).status()).toBe(412);

    // The tag covers the whole contact, so the dialog names what changed.
    const dialog = page.getByTestId('write-conflict-dialog');
    await expect(page.getByTestId('write-conflict-changed')).toHaveText(
      'Changed: Nickname.'
    );

    const reapplied = page.waitForResponse(isEmailEdit);
    await dialog.getByRole('button', { name: 'Keep mine' }).click();
    expect((await reapplied).status()).toBe(200);
    await expect(dialog).toBeHidden();

    await page.reload();
    await expect(
      page.getByRole('button', { name: /^Email address/ }).first()
    ).toContainText('john.new@example.com');
    await expect(page.getByTestId('nickname-field')).toContainText('Elsewhere');
  });
});
