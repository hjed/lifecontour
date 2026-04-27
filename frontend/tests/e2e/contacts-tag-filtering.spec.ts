import { test, expect } from './fixtures';

/**
 * Tag Filtering Tests — Unified Contacts List
 *
 * These tests verify that tag filtering works through the main contacts
 * list page at `/contacts?tag=<id>`. The old standalone `/contacts/tags/<id>`
 * page now redirects here.
 *
 * Converted to use the advanced fixture-based testing system.
 */
test.describe('Tag Filtering via Main Contacts List', () => {
  test('should redirect to login when not authenticated', async ({
    unauthenticatedPage,
  }) => {
    // Navigate to tag-filtered contacts page
    await unauthenticatedPage.goto('/contacts?tag=1');
    await expect(unauthenticatedPage).toHaveTitle(/Personal Management System/);

    // Should redirect to login first
    await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);

    // Then wait for the login form to appear
    await expect(
      unauthenticatedPage.getByRole('heading', { name: 'Welcome Back' })
    ).toBeVisible();

    // Should show OAuth button
    await expect(
      unauthenticatedPage.getByRole('button', { name: /continue with/i })
    ).toBeVisible();
  });

  test('legacy /contacts/tags/[id] redirects to /contacts?tag=<id>', async ({
    authenticatedPage,
  }) => {
    // Create a tag to test with
    const tagName = 'Redirect-Test-' + Date.now();
    const tagResp = await authenticatedPage.request.post('/api/tags', {
      data: {
        data: {
          type: 'tags',
          attributes: { name: tagName },
        },
      },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(tagResp.ok()).toBe(true);
    const tagData = await tagResp.json();
    const tagId = tagData.data.id;

    // Navigate to the old URL
    await authenticatedPage.goto(`/contacts/tags/${tagId}`);

    // Should redirect to the main contacts page with tag param
    await authenticatedPage.waitForURL(`**/contacts?tag=${tagId}`);
    expect(authenticatedPage.url()).toContain(`/contacts?tag=${tagId}`);

    // Cleanup
    await authenticatedPage.request.delete(`/api/tags/${tagId}`);
  });

  test('should display contacts filtered by tag when tag exists', async ({
    taggedContactsData,
    isMobile,
  }) => {
    if (isMobile) test.skip();
    const { page, contacts, tags } = taggedContactsData;
    // Navigate to contacts with tag filter (new unified URL)
    const firstTag = tags[0];
    await page.goto(`/contacts?tag=${firstTag.id}`);
    await expect(page).toHaveTitle(/Personal Management System/);

    // Should show contacts with this tag (guaranteed by fixture)
    const contactsWithTag = contacts.filter(
      c => c.tags && c.tags.includes(firstTag.name)
    );
    expect(contactsWithTag.length).toBeGreaterThan(0);

    // Should have proper heading with tag information
    const heading = page.locator('h1');
    await expect(heading).toBeVisible();
    await expect(heading).toContainText(new RegExp(firstTag.name, 'i'));

    // Verify contacts are displayed
    for (const contact of contactsWithTag) {
      const contactCard = page.locator(`[data-testid="contact-${contact.id}"]`);
      await expect(contactCard).toBeVisible();

      // Should have favourite button
      const favouriteButton = contactCard.locator(
        '[data-testid="favourite-toggle"]'
      );
      await expect(favouriteButton).toBeVisible();
    }
  });

  test('should handle non-existent tag gracefully', async ({
    authenticatedPage,
  }) => {
    // Navigate to a non-existent tag
    await authenticatedPage.goto('/contacts?tag=non-existent-tag-999');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // The page should load without errors — contacts list shows
    // with no results since the tag ID does not match any real tag
    const heading = authenticatedPage.locator('h1');
    await expect(heading).toBeVisible();
  });

  test('parent tag filter should show contacts tagged with child tags', async ({
    authenticatedPage,
  }) => {
    // 1. Create parent tag
    const parentName = 'ParentHier-' + Date.now();
    const parentResp = await authenticatedPage.request.post('/api/tags', {
      data: {
        data: {
          type: 'tags',
          attributes: { name: parentName },
        },
      },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(parentResp.ok()).toBe(true);
    const parentData = await parentResp.json();
    const parentId = parentData.data.id;

    // Ensure parent tag is fully committed to DB before using as parent_id to avoid CI race conditions
    await expect(async () => {
      const verifyResp = await authenticatedPage.request.get(
        `/api/tags/${parentId}`
      );
      expect(verifyResp.ok()).toBe(true);
    }).toPass({ timeout: 5000 });

    // 2. Create child tag with parent_id
    const childName = 'ChildHier-' + Date.now();
    const childResp = await authenticatedPage.request.post('/api/tags', {
      data: {
        data: {
          type: 'tags',
          attributes: { name: childName, parent_id: Number(parentId) },
        },
      },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(childResp.ok(), await childResp.text()).toBe(true);
    const childData = await childResp.json();
    const childId = childData.data.id;

    // 3. Create a contact
    const contactResp = await authenticatedPage.request.post('/api/contacts', {
      data: {
        data: {
          type: 'contacts',
          attributes: {
            first_name: 'HierTest',
            last_name: 'Contact-' + Date.now(),
          },
        },
      },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(contactResp.ok()).toBe(true);
    const contactData = await contactResp.json();
    const contactId = contactData.data.id;

    // 4. Assign child tag to contact
    const assignResp = await authenticatedPage.request.post(
      `/api/contacts/${contactId}/tags`,
      {
        data: { data: { type: 'tags', id: String(childId) } },
        headers: { 'Content-Type': 'application/json' },
      }
    );
    expect(assignResp.ok() || assignResp.status() === 204).toBe(true);

    // 5. Navigate to unified contacts page with parent tag filter
    await authenticatedPage.goto(`/contacts?tag=${parentId}`);
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // The contact should appear because filtering by parent includes descendants
    const contactCard = authenticatedPage.locator(
      `[data-testid="contact-${contactId}"]`
    );
    await expect(contactCard).toBeVisible({ timeout: 10000 });

    // Cleanup
    await authenticatedPage.request.delete(`/api/contacts/${contactId}`);
    await authenticatedPage.request.delete(`/api/tags/${childId}`);
    await authenticatedPage.request.delete(`/api/tags/${parentId}`);
  });

  test('flat tag filtering still works for tags without parents', async ({
    authenticatedPage,
  }) => {
    // 1. Create a simple flat tag (no parent)
    const tagName = 'FlatHier-' + Date.now();
    const tagResp = await authenticatedPage.request.post('/api/tags', {
      data: {
        data: {
          type: 'tags',
          attributes: { name: tagName },
        },
      },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(tagResp.ok()).toBe(true);
    const tagData = await tagResp.json();
    const tagId = tagData.data.id;

    // 2. Create and tag a contact
    const contactResp = await authenticatedPage.request.post('/api/contacts', {
      data: {
        data: {
          type: 'contacts',
          attributes: {
            first_name: 'FlatTest',
            last_name: 'Contact-' + Date.now(),
          },
        },
      },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(contactResp.ok()).toBe(true);
    const contactData = await contactResp.json();
    const contactId = contactData.data.id;

    const assignResp = await authenticatedPage.request.post(
      `/api/contacts/${contactId}/tags`,
      {
        data: { data: { type: 'tags', id: String(tagId) } },
        headers: { 'Content-Type': 'application/json' },
      }
    );
    expect(assignResp.ok() || assignResp.status() === 204).toBe(true);

    // 3. Navigate to the unified contacts page with tag filter
    await authenticatedPage.goto(`/contacts?tag=${tagId}`);
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // The contact should be visible
    const contactCard = authenticatedPage.locator(
      `[data-testid="contact-${contactId}"]`
    );
    await expect(contactCard).toBeVisible({ timeout: 10000 });

    // Cleanup
    await authenticatedPage.request.delete(`/api/contacts/${contactId}`);
    await authenticatedPage.request.delete(`/api/tags/${tagId}`);
  });

  test('should show tag name in page header when tag exists', async ({
    authenticatedPage,
  }) => {
    // Create a test tag
    const tagName = 'Header-Test-Tag-' + Date.now();
    const response = await authenticatedPage.request.post('/api/tags', {
      data: {
        data: {
          type: 'tags',
          attributes: {
            name: tagName,
          },
        },
      },
      headers: {
        'Content-Type': 'application/json',
      },
    });

    expect(response.ok()).toBe(true);
    const responseData = await response.json();
    const tagId = responseData.data.id;

    await authenticatedPage.goto(`/contacts?tag=${tagId}`);
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Wait for the heading to contain the tag name — this is loaded
    // asynchronously via the useTags() query, so we use Playwright's
    // web-first assertion which auto-retries until the text appears.
    const heading = authenticatedPage.locator('h1');
    await expect(heading).toContainText(tagName, { ignoreCase: true });

    // Cleanup test data
    await authenticatedPage.request.delete(`/api/tags/${tagId}`);
  });

  test('should show active tag badge with clear functionality', async ({
    authenticatedPage,
  }) => {
    // Create a test tag
    const tagName = 'Badge-Test-' + Date.now();
    const response = await authenticatedPage.request.post('/api/tags', {
      data: {
        data: {
          type: 'tags',
          attributes: { name: tagName },
        },
      },
      headers: { 'Content-Type': 'application/json' },
    });
    expect(response.ok()).toBe(true);
    const responseData = await response.json();
    const tagId = responseData.data.id;

    await authenticatedPage.goto(`/contacts?tag=${tagId}`);
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Active tag badge should be visible
    const tagBadge = authenticatedPage.locator(
      '[data-testid="active-tag-filter"]'
    );
    await expect(tagBadge).toBeVisible({ timeout: 10000 });

    // Click clear to remove tag filter
    const clearButton = authenticatedPage.locator(
      '[data-testid="clear-tag-filter"]'
    );
    await expect(clearButton).toBeVisible();
    await clearButton.click();

    // Should return to unfiltered contacts list
    await authenticatedPage.waitForURL('**/contacts');
    expect(authenticatedPage.url()).not.toContain('tag=');

    // Tag badge should no longer be visible
    await expect(tagBadge).not.toBeVisible();

    // Cleanup
    await authenticatedPage.request.delete(`/api/tags/${tagId}`);
  });

  test('should maintain consistent navigation with other contact pages', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts?tag=1');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Should have consistent navigation elements (sidebar)
    const sidebar = authenticatedPage
      .locator('nav, aside, [role="navigation"]')
      .first();
    await expect(sidebar).toBeVisible();

    // Should have navigation back to all contacts
    const allContactsLink = authenticatedPage.locator('a[href="/contacts"]');
    if ((await allContactsLink.count()) > 0) {
      await expect(allContactsLink.first()).toBeVisible();
    }

    // Should have favourites link
    const favouritesLink = authenticatedPage.locator(
      'a[href="/contacts/favourites"]'
    );
    if ((await favouritesLink.count()) > 0) {
      await expect(favouritesLink.first()).toBeVisible();
    }
  });
});
