import { test, expect } from './fixtures';

import { SidebarTestHelpers } from './utils/test-helpers';

test.describe('Tag CRUD UI Updates', () => {
  test('tag creation, update, and deletion reflects in sidebar', async ({
    authenticatedPage,
  }) => {
    // Generate a unique ID to avoid conflicts
    const uniqueHash = Date.now().toString();
    const tagName = 'CrudTest-' + uniqueHash;
    let tagId = '';

    const sidebarHelpers = new SidebarTestHelpers(authenticatedPage);

    // Navigate to contacts page
    await authenticatedPage.goto('/contacts');

    // Create Tag via API
    const createResp = await authenticatedPage.request.post('/api/tags', {
      data: {
        data: {
          type: 'tags',
          attributes: { name: tagName },
        },
      },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(createResp.ok()).toBe(true);
    const tagData = await createResp.json();
    tagId = tagData.data.id;

    // Use try-finally but without 'if' to please the linter.
    // By initializing tagId with a fallback value ('0' or the actual id),
    // we can always execute the delete without a branch.
    try {
      // Reload page and poll until it appears in sidebar
      await expect(async () => {
        await authenticatedPage.reload();
        await sidebarHelpers.waitForSidebar();

        const tagLink = authenticatedPage
          .locator(`a[href*="/contacts?tag=${tagId}"]`)
          .filter({ hasText: new RegExp(tagName, 'i') })
          .first();
        await expect(tagLink).toBeVisible();
      }).toPass({ timeout: 15000 });

      // Update Tag via API
      const newTagName = tagName + '-Updated';
      const updateResp = await authenticatedPage.request.patch(
        `/api/tags/${tagId}`,
        {
          data: {
            data: {
              type: 'tags',
              id: String(tagId),
              attributes: { name: newTagName },
            },
          },
          headers: { 'Content-Type': 'application/json' },
        }
      );
      expect(updateResp.ok()).toBe(true);

      // Reload page and poll until the new text appears
      await expect(async () => {
        await authenticatedPage.reload();
        await sidebarHelpers.waitForSidebar();

        const tagLink = authenticatedPage
          .locator(`a[href*="/contacts?tag=${tagId}"]`)
          .filter({ hasText: new RegExp(newTagName, 'i') })
          .first();
        await expect(tagLink).toBeVisible();
      }).toPass({ timeout: 15000 });

      // Delete Tag via API
      const deleteResp = await authenticatedPage.request.delete(
        `/api/tags/${tagId}`
      );
      expect(deleteResp.ok()).toBe(true);

      // Reload page and poll until it disappears
      await expect(async () => {
        await authenticatedPage.reload();
        await sidebarHelpers.waitForSidebar();

        const tagLink = authenticatedPage.locator(
          `a[href*="/contacts?tag=${tagId}"]`
        );
        await expect(tagLink).toHaveCount(0);
      }).toPass({ timeout: 15000 });
    } finally {
      if (tagId) {
        // Only delete if we actually got a valid tag ID back
        await authenticatedPage.request.delete(`/api/tags/${tagId}`);
      }
    }
  });
});
