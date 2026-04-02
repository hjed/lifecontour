import { test, expect } from './fixtures';

test.describe('Tag CRUD UI Updates', () => {
  test('tag creation, update, and deletion reflects in sidebar', async ({
    authenticatedPage,
  }) => {
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

    // Reload page to see it in sidebar
    await authenticatedPage.reload();
    const tagLink = authenticatedPage.locator(
      `a[href*="/contacts?tag=${tagId}"]`
    );
    await expect(tagLink).toBeVisible();
    await expect(tagLink).toHaveText(new RegExp(tagName, 'i'));

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

    // Reload page
    await authenticatedPage.reload();
    await expect(tagLink).toBeVisible();
    await expect(tagLink).toHaveText(new RegExp(newTagName, 'i'));

    // Delete Tag via API
    const deleteResp = await authenticatedPage.request.delete(
      `/api/tags/${tagId}`
    );
    expect(deleteResp.ok()).toBe(true);

    // Reload page
    await authenticatedPage.reload();
    await expect(tagLink).not.toBeVisible();
  });
});
