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

  test('should allow editing a template name and pitches', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    // 1. Create a template with a pitch via API
    const templateName = `E2E Edit Template ${Date.now()}`;
    const templateRes = await page.request.post('/api/templates', {
      data: {
        data: {
          type: 'activity-templates',
          attributes: {
            name: templateName,
            template_type: 'canyoning',
            region: 'Blue Mountains',
            pitches: [{ pitch_number: 1, height: 20, notes: 'Wet start' }],
          },
        },
      },
    });
    expect(templateRes.ok()).toBeTruthy();
    const templateId = (await templateRes.json()).data.id as string;

    // 2. Open the edit dialog from settings
    await page.goto('/settings');
    const templateRow = page.locator(`[data-testid^="template-row-"]`, {
      hasText: templateName,
    });
    await expect(templateRow).toBeVisible();
    await templateRow
      .getByRole('button', { name: `Edit template ${templateName}` })
      .click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Template Name')).toHaveValue(templateName);
    await expect(dialog.getByLabel('Notes for pitch 1')).toHaveValue(
      'Wet start'
    );

    // 3. Rename, tweak the pitch, and save
    const updatedName = `${templateName} v2`;
    await dialog.getByLabel('Template Name').fill(updatedName);
    await dialog.getByLabel('Height for pitch 1').fill('35');
    await Promise.all([
      page.waitForResponse(
        resp =>
          resp.url().includes('/api/templates') &&
          resp.request().method() === 'PUT' &&
          resp.ok()
      ),
      dialog.getByRole('button', { name: 'Save Changes' }).click(),
    ]);

    await expect(dialog).toBeHidden();
    await expect(page.getByText('Template updated successfully')).toBeVisible();

    // 4. Reload and verify the change persisted
    await page.reload();
    const updatedRow = page.locator(`[data-testid^="template-row-"]`, {
      hasText: updatedName,
    });
    await expect(updatedRow).toBeVisible();
    await updatedRow
      .getByRole('button', { name: `Edit template ${updatedName}` })
      .click();
    await expect(
      page.getByRole('dialog').getByLabel('Height for pitch 1')
    ).toHaveValue('35');

    // Clean up the template so it doesn't leak into later e2e runs.
    const deleteRes = await page.request.delete(`/api/templates/${templateId}`);
    expect(deleteRes.ok()).toBeTruthy();
  });
});
