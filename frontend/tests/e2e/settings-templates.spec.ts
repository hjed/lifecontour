import { test, expect } from './fixtures';

test.describe('Settings - Template Management', () => {
  test('should allow creating, listing, and deleting templates', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    // 1. Create a template via API to ensure we have one to delete
    const templateName = `E2E Deletion Template ${Date.now()}`;
    const templateRes = await page.request.post('/api/templates', {
      data: {
        data: {
          type: 'activity-templates',
          attributes: {
            name: templateName,
            template_type: 'canyoning',
            region: 'Blue Mountains',
          },
        },
      },
    });
    expect(templateRes.ok()).toBeTruthy();

    // 2. Navigate to settings page
    await page.goto('/settings');

    // 3. Find the template in the list
    const templateRow = page.locator(`[data-testid^="template-row-"]`, {
      hasText: templateName,
    });
    await expect(templateRow).toBeVisible();

    // 4. Click delete button
    const deleteBtn = templateRow.getByRole('button', {
      name: /delete template/i,
    });
    await deleteBtn.click();

    // 5. Confirm deletion in dialog
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    let deletePostFinished = false;
    await Promise.all([
      page.waitForResponse(resp => {
        if (
          resp.url().includes('/api/templates') &&
          resp.request().method() === 'DELETE' &&
          resp.ok()
        ) {
          deletePostFinished = true;
          return true;
        }
        return false;
      }),
      page.waitForResponse(
        resp =>
          deletePostFinished &&
          resp.url().includes('/api/templates') &&
          resp.request().method() === 'GET' &&
          resp.ok()
      ),
      dialog.getByRole('button', { name: /delete/i }).click(),
    ]);

    // Wait for dialog to close
    await expect(dialog).toBeHidden();

    // 6. Verify success toast and template disappearance
    await expect(page.getByText('Template deleted successfully')).toBeVisible();
    await expect(templateRow).toBeHidden({ timeout: 15000 });
  });
});
