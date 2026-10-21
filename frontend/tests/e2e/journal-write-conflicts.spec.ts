import { test, expect } from './fixtures';

/**
 * Conditional writes on the journal page (#1812): edits send the journal's
 * ETag as If-Match, so an edit made against a stale copy is refused (412) and
 * the conflict dialog offers to re-apply it. The tag covers the whole journal,
 * so a change to another part of it is enough to refuse the edit.
 */
test.describe('Journal write conflicts', () => {
  test('a title edit against a stale copy is refused, and Keep mine re-applies it', async ({
    journalsWithData,
  }) => {
    const { page, journals } = journalsWithData;
    const journal = journals[0];

    await page.goto(`/journals/${journal.id}`);
    const titleField = page.getByTestId('journal-title-field');
    await expect(titleField).toContainText(journal.title);

    // Another tab changes the journal's content after this page read it.
    const elsewhere = await page.request.patch(`/api/journals/${journal.id}`, {
      data: {
        data: {
          type: 'journals',
          id: journal.id,
          attributes: { content: 'Changed elsewhere' },
        },
      },
    });
    expect(elsewhere.status()).toBe(200);

    const isTitleSave = (res: {
      url(): string;
      request(): { method(): string };
    }) =>
      res.url().endsWith(`/api/journals/${journal.id}`) &&
      res.request().method() === 'PATCH';

    const refused = page.waitForResponse(isTitleSave);
    await titleField.click();
    const titleInput = page.getByTestId('journal-title-field-input');
    await expect(titleInput).toBeVisible();
    await titleInput.fill('My title');
    await page.getByRole('button', { name: 'Save changes' }).click();
    expect((await refused).status()).toBe(412);

    const dialog = page.getByTestId('write-conflict-dialog');
    await expect(dialog).toContainText(
      'This journal was changed on another tab or device'
    );
    await expect(page.getByTestId('write-conflict-changed')).toHaveText(
      'Changed: Content.'
    );

    const reapplied = page.waitForResponse(isTitleSave);
    await dialog.getByRole('button', { name: 'Keep mine' }).click();
    expect((await reapplied).status()).toBe(200);
    await expect(dialog).toBeHidden();

    // Both changes persisted.
    await page.reload();
    await expect(page.getByTestId('journal-title-field')).toContainText(
      'My title'
    );
    await expect(page.getByText('Changed elsewhere')).toBeVisible();
  });
});
