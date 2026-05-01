import { test, expect } from './fixtures';

test.describe('Tag CRUD UI Updates', () => {
  test('tag creation, update, and deletion reflects in sidebar', async ({
    authenticatedPage,
  }) => {
    let cleanupTagId: string | null = null;

    try {
      // Navigate to contacts page
      await authenticatedPage.goto('/contacts');

      // Create Tag via API
      const tagName = 'CrudTest-' + Date.now();
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
      const tagId = tagData.data.id;
      cleanupTagId = tagId;

      // Helper to open sidebar on mobile
      const ensureSidebarVisible = async () => {
        const hamburgerButton = authenticatedPage.locator(
          'button[aria-label*="menu"], button[aria-label*="navigation"]'
        );
        if (
          (await hamburgerButton.count()) > 0 &&
          (await hamburgerButton.first().isVisible())
        ) {
          await hamburgerButton.first().click();
        }
      };

      // Reload page and poll until it appears in sidebar to handle caching/latency
      const tagLink = authenticatedPage.locator(
        `a[href*="/contacts?tag=${tagId}"]`
      );
      await expect(async () => {
        await authenticatedPage.reload();
        await ensureSidebarVisible();
        await expect(tagLink).toBeVisible();
        await expect(tagLink).toHaveText(new RegExp(tagName, 'i'));
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
        await ensureSidebarVisible();
        await expect(tagLink).toBeVisible();
        await expect(tagLink).toHaveText(new RegExp(newTagName, 'i'));
      }).toPass({ timeout: 15000 });

      // Delete Tag via API
      const deleteResp = await authenticatedPage.request.delete(
        `/api/tags/${tagId}`
      );
      expect(deleteResp.ok()).toBe(true);
      cleanupTagId = null; // Cleaned up cleanly during standard execution

      // Reload page and poll until it disappears
      await expect(async () => {
        await authenticatedPage.reload();
        await ensureSidebarVisible();
        await expect(tagLink).not.toBeVisible();
      }).toPass({ timeout: 15000 });
    } finally {
      if (cleanupTagId) {
        await authenticatedPage.request.delete(`/api/tags/${cleanupTagId}`);
      }
    }
  });
});
