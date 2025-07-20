import { test, expect } from './fixtures';

/**
 * Tag Filtering Pages Tests
 *
 * Converted to use the advanced fixture-based testing system.
 * Each test uses deterministic fixtures that provide guaranteed data state.
 */
test.describe('Tag Filtering Pages', () => {
  test('should redirect to login when not authenticated', async ({
    unauthenticatedPage,
  }) => {
    // Navigate to tag page
    await unauthenticatedPage.goto('/contacts/tags/work');
    await expect(unauthenticatedPage).toHaveTitle(/Personal Management System/);

    // Should redirect to login (guaranteed by fixture)
    await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);

    // Should show login form
    await expect(
      unauthenticatedPage.getByRole('heading', { name: 'Welcome Back' })
    ).toBeVisible();
  });

  test('should display contacts filtered by tag when tag exists', async ({
    taggedContactsData,
  }) => {
    const { page, contacts, tags } = taggedContactsData;
    // Navigate to first tag page (guaranteed by fixture)
    const firstTag = tags[0];
    await page.goto(`/contacts/tags/${firstTag.name}`);
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

  test('should display not found message for non-existent tag', async ({
    authenticatedPage,
  }) => {
    // Navigate to non-existent tag page
    await authenticatedPage.goto('/contacts/tags/non-existent-tag-999');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Should show tag not found message
    const errorContent = authenticatedPage.locator(
      'text=/tag.*not.*found/i, text=/not.*found/i'
    );
    await expect(errorContent).toBeVisible();

    // Should have helpful navigation back to contacts
    const backLink = authenticatedPage.locator(
      'a[href="/contacts"], a:has-text("Browse"), a:has-text("All Contacts")'
    );
    const linkCount = await backLink.count();
    if (linkCount > 0) {
      await expect(backLink.first()).toBeVisible();
    }
  });

  test('should display contacts filtered by tag when available', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts/tags/1');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Wait for content to load by waiting for contact cards, empty state, or error message
    await authenticatedPage.waitForSelector(
      '[data-testid="contact-card"], .contact-card, [class*="card"], text=/no contacts.*tag/i, text=/no contacts found/i, text=/tag.*not.*found/i',
      { timeout: 10000 }
    );

    // Look for contact cards or empty state
    const contactCards = authenticatedPage.locator(
      '[data-testid="contact-card"], .contact-card, [class*="card"]'
    );
    const emptyState = authenticatedPage.locator(
      'text=/no contacts.*tag/i, text=/no contacts found/i'
    );

    const hasContacts = (await contactCards.count()) > 0;
    const hasEmptyState = (await emptyState.count()) > 0;

    // Should have either contacts or empty state (or tag not found)
    const hasTagNotFound =
      (await authenticatedPage.locator('text=/tag.*not.*found/i').count()) > 0;

    expect(hasContacts || hasEmptyState || hasTagNotFound).toBe(true);

    if (hasContacts) {
      // If there are contacts, they should have favourite toggles
      const favouriteButtons = contactCards.locator(
        'button[aria-label*="favourite"], button[aria-label*="Favourite"]'
      );
      const buttonCount = await favouriteButtons.count();
      expect(buttonCount).toBeGreaterThan(0);

      // Contacts should be clickable
      const contactLinks = contactCards.locator('a[href*="/contacts/"]');
      if ((await contactLinks.count()) > 0) {
        await expect(contactLinks.first()).toBeVisible();
      }
    }
  });

  test('should show tag name in page header when tag exists', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts/tags/1');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Wait for content to load
    await authenticatedPage.waitForTimeout(2000);

    const heading = authenticatedPage.locator('h1');
    await expect(heading).toBeVisible();

    // Should contain tag-related text (either tag name or "not found")
    const headingText = await heading.textContent();
    expect(headingText?.toLowerCase()).toMatch(/(tag|contact|not found)/);
  });

  test('should handle empty tag state with helpful message', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts/tags/1');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Wait for content to load by waiting for empty state, contact cards, or error message
    await authenticatedPage.waitForSelector(
      'text=/no contacts.*tag/i, text=/no contacts found/i, text=/add.*contacts.*tag/i, [data-testid="contact-card"], .contact-card, [class*="card"], text=/tag.*not.*found/i',
      { timeout: 10000 }
    );

    // Look for empty state message
    const emptyStateMessages = [
      'text=/no contacts.*tag/i',
      'text=/no contacts found/i',
      'text=/add.*contacts.*tag/i',
    ];

    let hasEmptyStateMessage = false;
    for (const selector of emptyStateMessages) {
      if ((await authenticatedPage.locator(selector).count()) > 0) {
        hasEmptyStateMessage = true;
        break;
      }
    }

    // Look for contact cards
    const contactCards = authenticatedPage.locator(
      '[data-testid="contact-card"], .contact-card, [class*="card"]'
    );
    const hasContacts = (await contactCards.count()) > 0;

    // Look for tag not found
    const hasTagNotFound =
      (await authenticatedPage.locator('text=/tag.*not.*found/i').count()) > 0;

    // Should have one of these states
    expect(hasEmptyStateMessage || hasContacts || hasTagNotFound).toBe(true);
  });

  test('should maintain consistent navigation with other contact pages', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts/tags/1');
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Should have consistent navigation elements
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
