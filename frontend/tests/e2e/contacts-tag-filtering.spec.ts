import { test, expect } from './fixtures';
import { APP_TITLE_PATTERN } from './utils/test-helpers';

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
    await expect(unauthenticatedPage).toHaveTitle(APP_TITLE_PATTERN);

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
    await expect(page).toHaveTitle(APP_TITLE_PATTERN);

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

    // Ensure contact is fully committed before assigning tag
    await expect(async () => {
      const verifyResp = await authenticatedPage.request.get(
        `/api/contacts/${contactId}`
      );
      expect(verifyResp.ok()).toBe(true);
    }).toPass({ timeout: 10000 });

    // 4. Assign child tag to contact
    await expect(async () => {
      const assignResp = await authenticatedPage.request.post(
        `/api/contacts/${contactId}/tags`,
        {
          data: { data: { type: 'tags', id: String(childId) } },
          headers: { 'Content-Type': 'application/json' },
        }
      );
      expect(assignResp.ok()).toBe(true);
    }).toPass({ timeout: 5000 });

    // 5. Navigate to unified contacts page with parent tag filter
    await authenticatedPage.goto(`/contacts?tag=${parentId}`);
    await expect(authenticatedPage).toHaveTitle(APP_TITLE_PATTERN);

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

    // Ensure both tag and contact are fully committed before assigning
    await expect(async () => {
      const verifyTag = await authenticatedPage.request.get(
        `/api/tags/${tagId}`
      );
      expect(verifyTag.ok()).toBe(true);
    }).toPass({ timeout: 5000 });

    await expect(async () => {
      const verifyContact = await authenticatedPage.request.get(
        `/api/contacts/${contactId}`
      );
      expect(verifyContact.ok()).toBe(true);
    }).toPass({ timeout: 10000 });

    await expect(async () => {
      const assignResp = await authenticatedPage.request.post(
        `/api/contacts/${contactId}/tags`,
        {
          data: { data: { type: 'tags', id: String(tagId) } },
          headers: { 'Content-Type': 'application/json' },
        }
      );
      expect(assignResp.ok()).toBe(true);
    }).toPass({ timeout: 5000 });

    // 3. Navigate to the unified contacts page with tag filter
    await authenticatedPage.goto(`/contacts?tag=${tagId}`);
    await expect(authenticatedPage).toHaveTitle(APP_TITLE_PATTERN);

    // The contact should be visible
    const contactCard = authenticatedPage.locator(
      `[data-testid="contact-${contactId}"]`
    );
    await expect(contactCard).toBeVisible({ timeout: 10000 });

    // Cleanup
    await authenticatedPage.request.delete(`/api/contacts/${contactId}`);
    await authenticatedPage.request.delete(`/api/tags/${tagId}`);
  });

  // Note: the tag name in the page header, the active-tag badge with its
  // clear button (including the ID fallback for an unresolved tag name), and
  // the empty/unknown-tag states are unit-tested in the ContactsPage tag
  // filtering block of app/contacts/__tests__/page.test.tsx. The tag filter's
  // real backend behaviour stays covered by the filter tests above.

  test('should maintain consistent navigation with other contact pages', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts?tag=1');
    await expect(authenticatedPage).toHaveTitle(APP_TITLE_PATTERN);

    // Should have consistent navigation elements (sidebar)
    const { SidebarTestHelpers } = await import('./utils/test-helpers');
    const sidebarHelpers = new SidebarTestHelpers(authenticatedPage);

    // Should have navigation back to all contacts
    await sidebarHelpers.testAllContactsLink();

    // Should have favourites link
    await sidebarHelpers.testFavouritesLink();
  });
});
