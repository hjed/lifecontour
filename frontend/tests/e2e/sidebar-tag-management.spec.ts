import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';
import { TestDataManager } from './data-management';

/**
 * Ensure the sidebar is visible and the Contacts section is expanded.
 * On mobile viewports, this opens the hamburger Sheet first.
 */
async function ensureSidebarOpen(page: Page) {
  const isMobile =
    page.viewportSize()?.width && page.viewportSize()!.width < 768;
  if (isMobile) {
    const mobileTrigger = page.getByTestId('mobile-nav-trigger');
    const isSidebarVisible = await page
      .getByRole('heading', { name: 'Navigation' })
      .isVisible();
    if (!isSidebarVisible) {
      await mobileTrigger.click();
      await expect(
        page.getByRole('heading', { name: 'Navigation' })
      ).toBeVisible();
    }
  }

  // Expand Contacts section if collapsed
  const sectionHeader = page.getByRole('button', { name: 'Contacts' });
  await expect(sectionHeader).toBeVisible();
  const isExpanded = await sectionHeader.getAttribute('aria-expanded');
  if (isExpanded === 'false') {
    await sectionHeader.click();
  }
}

test.describe('Sidebar Tag Management', () => {
  test('can create a new tag from the sidebar', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const testDataManager = new TestDataManager(page);
    const uniqueTagName = `New-Sidebar-Tag-${Date.now()}`;

    testCleanup(
      async () => await testDataManager.deleteTagByName(uniqueTagName)
    );

    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    // Click Create Tag button
    await page.getByRole('button', { name: 'Create Tag' }).click();

    // Fill out the dialog
    const dialog = page.getByRole('dialog', { name: 'Create Tag' });
    await expect(dialog).toBeVisible();

    await dialog.getByLabel('Name').fill(uniqueTagName);
    await dialog.getByPlaceholder('#000000').fill('#123456');
    await dialog.getByLabel('Description').fill('Created from sidebar');

    // Submit
    await dialog.getByRole('button', { name: 'Create Tag' }).click();

    // Verify dialog closes
    await expect(dialog).not.toBeVisible();

    // Verify Toast appears
    await expect(page.getByText('Tag created successfully')).toBeVisible();

    // On mobile the Sheet may have closed after the dialog interaction,
    // so re-open the sidebar before checking for the new tag link.
    await ensureSidebarOpen(page);

    // Verify tag appears in sidebar (may require React Query refetch + re-render)
    const tagLink = page.getByRole('link', {
      name: uniqueTagName,
      exact: true,
    });
    await expect(tagLink).toBeVisible({ timeout: 15000 });
  });

  test('can open context menu and edit a tag', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    const tagName = `Tag-To-Edit-${Date.now()}`;
    const newTagName = `Edited-Tag-Name-${Date.now()}`;

    await dataManager.createTags([{ name: tagName }]);
    testCleanup(async () => await dataManager.cleanup());

    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    // Wait for the tag to be visible
    const tagLink = page.getByRole('link', { name: tagName, exact: true });
    await expect(tagLink).toBeVisible();

    // Right click the tag item
    await tagLink.click({ button: 'right' });

    // Wait for context menu item
    const editMenuItem = page.getByRole('menuitem', { name: 'Edit Tag' });
    await expect(editMenuItem).toBeVisible();

    // Click edit
    await editMenuItem.click();

    // Dialog should appear
    const dialog = page.getByRole('dialog', { name: 'Edit Tag' });
    await expect(dialog).toBeVisible();

    // Update name
    await dialog.getByLabel('Name').fill(newTagName);

    // Submit
    await dialog.getByRole('button', { name: 'Save Changes' }).click();

    // Verify toast
    await expect(page.getByText('Tag updated successfully')).toBeVisible();

    // Re-open sidebar on mobile to verify updated tag
    await ensureSidebarOpen(page);

    // Verify updated tag appears in sidebar
    await expect(
      page.getByRole('link', { name: newTagName, exact: true })
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByRole('link', { name: tagName, exact: true })
    ).not.toBeVisible({ timeout: 10000 });
  });

  test('can delete a tag from the edit dialog', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    const tagName = `Tag-To-Delete-${Date.now()}`;

    await dataManager.createTags([{ name: tagName }]);
    testCleanup(async () => await dataManager.cleanup());

    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    const tagLink = page.getByRole('link', { name: tagName, exact: true });
    await expect(tagLink).toBeVisible();

    // Right click and edit
    await tagLink.click({ button: 'right' });
    await page.getByRole('menuitem', { name: 'Edit Tag' }).click();

    const dialog = page.getByRole('dialog', { name: 'Edit Tag' });
    await expect(dialog).toBeVisible();

    // Click delete
    await dialog.getByRole('button', { name: 'Delete Tag' }).click();

    // Alert dialog should appear
    const alertDialog = page.getByRole('alertdialog');
    await expect(alertDialog).toBeVisible();
    await expect(alertDialog).toContainText('Are you absolutely sure?');

    // Confirm delete
    await alertDialog.getByRole('button', { name: 'Delete' }).click();

    // Verify toast
    await expect(page.getByText('Tag deleted successfully')).toBeVisible();

    // Re-open sidebar on mobile to verify tag removed
    await ensureSidebarOpen(page);

    // Verify tag disappears from sidebar
    await expect(
      page.getByRole('link', { name: tagName, exact: true })
    ).not.toBeVisible({ timeout: 10000 });
  });

  test('create dialog validates required fields', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    await page.getByRole('button', { name: 'Create Tag' }).click();

    const dialog = page.getByRole('dialog', { name: 'Create Tag' });
    await expect(dialog).toBeVisible();

    // Submit empty form
    await dialog.getByRole('button', { name: 'Create Tag' }).click();

    // Should see validation error
    await expect(dialog.getByText('Name is required')).toBeVisible();

    // Dialog should stay open
    await expect(dialog).toBeVisible();
  });

  test('edit dialog validates required fields', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    const tagName = `Tag-For-Validation-${Date.now()}`;

    await dataManager.createTags([{ name: tagName }]);
    testCleanup(async () => await dataManager.cleanup());

    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    const tagLink = page.getByRole('link', { name: tagName, exact: true });
    await expect(tagLink).toBeVisible();

    await tagLink.click({ button: 'right' });
    await page.getByRole('menuitem', { name: 'Edit Tag' }).click();

    const dialog = page.getByRole('dialog', { name: 'Edit Tag' });
    await expect(dialog).toBeVisible();

    // Clear name
    await dialog.getByLabel('Name').fill('');

    // Submit
    await dialog.getByRole('button', { name: 'Save Changes' }).click();

    // Should see validation error
    await expect(dialog.getByText('Name is required')).toBeVisible();
  });
});
