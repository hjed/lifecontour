import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Contact Management - Authenticated User', () => {
  test('should load contacts page successfully when authenticated', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts');

    // Verify the page loads successfully
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Should be on contacts page, not redirected to login
    await expect(authenticatedPage).toHaveURL(/\/contacts/);

    // Should see contacts page content
    const pageContent = await authenticatedPage.textContent('body');
    expect(pageContent).toContain('Contacts');
  });

  test('should load create contact page successfully when authenticated', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts/new');

    // Verify the page loads successfully
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);
    await expect(authenticatedPage).toHaveURL(/\/contacts\/new/);

    // Should see create contact form
    const pageContent = authenticatedPage.locator('body');
    await expect(pageContent).not.toBeEmpty();
  });

  test('should display contact details with tags properly', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    const contact = await dataManager.createContact({
      firstName: 'Tagged',
      lastName: 'Contact',
      tags: ['TestDetailTag'],
    });

    testCleanup(async () => {
      await authenticatedPage.request.delete(`/api/contacts/${contact.id}`);
    });

    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Verify page loads without error 418 or other crashes
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Check that contact name is loaded
    await expect(
      authenticatedPage.getByText(`${contact.firstName} ${contact.lastName}`)
    ).toBeVisible({ timeout: 10000 });

    // Verify tag is displayed using the specific text (since we don't know the exact new tag ID)
    await expect(
      authenticatedPage
        .locator('[data-testid^="tag-badge-"]:visible', {
          hasText: 'TestDetailTag',
        })
        .first()
    ).toBeVisible({ timeout: 10000 });
  });

  test('should load contact details page successfully when authenticated', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts/123');

    // Verify the page loads successfully
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Page should load (might show 404 for non-existent contact, but that's valid)
    const pageContent = authenticatedPage.locator('body');
    await expect(pageContent).not.toBeEmpty();
  });

  test('should handle navigation between contact pages when authenticated', async ({
    authenticatedPage,
  }) => {
    // Navigate to contacts page
    await authenticatedPage.goto('/contacts');
    await expect(authenticatedPage).toHaveURL(/\/contacts/);

    // Navigate to create page
    await authenticatedPage.goto('/contacts/new');
    await expect(authenticatedPage).toHaveURL(/\/contacts\/new/);

    // Navigate back to contacts
    await authenticatedPage.goto('/contacts');
    await expect(authenticatedPage).toHaveURL(/\/contacts/);

    // Verify content is present
    const bodyText = authenticatedPage.locator('body');
    await expect(bodyText).not.toBeEmpty();
  });

  test('should display tag names (not IDs) on contact cards in the list view', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);
    const tagName = 'ListViewTag';

    const contact = await dataManager.createContact({
      firstName: 'TagDisplay',
      lastName: 'Test',
      tags: [tagName],
    });

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    await authenticatedPage.goto('/contacts');

    const contactCard = authenticatedPage.getByTestId(`contact-${contact.id}`);
    await expect(contactCard).toBeVisible({ timeout: 10000 });

    // Tag should show its name, not "Tag {id}"
    await expect(contactCard.getByTestId(`tag-${tagName}`)).toBeVisible({
      timeout: 10000,
    });

    // Should NOT show fallback "Tag <number>" pattern
    const tagBadges = contactCard.locator('[data-testid^="tag-Tag "]');
    await expect(tagBadges).toHaveCount(0);
  });

  test('should load contacts beyond the first page with infinite scroll', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    const totalContacts = 25;

    await page.setViewportSize({ width: 1280, height: 720 });
    await dataManager.clearAllContacts();

    const contacts = await dataManager.createContacts(
      Array.from({ length: totalContacts }, (_, index) => ({
        firstName: `PagedContact${String(index + 1).padStart(2, '0')}`,
        lastName: 'InfiniteScroll',
      }))
    );

    testCleanup(async () => {
      for (const contact of contacts) {
        const response = await page.request.delete(
          `/api/contacts/${contact.id}`
        );

        if (!response.ok() && response.status() !== 404) {
          throw new Error(
            `Failed to delete contact ${contact.id}: ${response.status()}`
          );
        }
      }
    });

    await page.goto('/contacts');
    await expect(page).toHaveTitle(/Personal Management System/);
    await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText(`${totalContacts} contacts found`)).toBeVisible(
      { timeout: 10000 }
    );

    const contactCards = page.locator('[data-testid^="contact-"]');
    await expect.poll(async () => contactCards.count()).toBe(20);

    const laterPageContactSource = contacts[24];

    if (!laterPageContactSource) {
      throw new Error('Expected a contact beyond the first page');
    }

    const laterPageContact = page.getByTestId(
      `contact-${laterPageContactSource.id}`
    );
    await expect(laterPageContact).toHaveCount(0);

    const infiniteScrollTrigger = page.getByTestId(
      'contacts-infinite-scroll-trigger'
    );
    await expect(infiniteScrollTrigger).toBeVisible({ timeout: 10000 });
    await infiniteScrollTrigger.scrollIntoViewIfNeeded();

    await expect.poll(async () => contactCards.count()).toBe(totalContacts);
    await expect(laterPageContact).toBeVisible({ timeout: 10000 });
  });

  test('should display relationship with linked contact name and clickable link', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Create two contacts
    const contacts = await dataManager.createContacts([
      { firstName: 'Alice', lastName: 'RelTest' },
      { firstName: 'Bob', lastName: 'RelTest' },
    ]);

    const alice = contacts[0];
    const bob = contacts[1];

    if (!alice || !bob) {
      throw new Error('Failed to create test contacts');
    }

    // Create a relationship: Alice -> Bob (partner)
    await dataManager.createRelationship(alice.id, bob.id, 'partner');

    testCleanup(async () => {
      await dataManager.cleanup();
    });

    // Navigate to Alice's detail page
    await authenticatedPage.goto(`/contacts/${alice.id}`);
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Wait for the contact name to be visible
    await expect(
      authenticatedPage
        .getByText(`${alice.firstName} ${alice.lastName}`)
        .first()
    ).toBeVisible({ timeout: 10000 });

    // Verify the Relationships section is visible
    await expect(
      authenticatedPage.getByRole('heading', { name: 'Relationships' })
    ).toBeVisible({ timeout: 10000 });

    // Verify the relationship type is shown
    await expect(
      authenticatedPage.getByText('Partner', { exact: true })
    ).toBeVisible({
      timeout: 10000,
    });

    // Verify the linked contact name is shown and is a link
    const contactLink = authenticatedPage.getByTestId(
      `relationship-contact-link-${bob.id}`
    );
    await expect(contactLink).toBeVisible({ timeout: 10000 });
    await expect(contactLink).toContainText(bob.firstName);

    // Click the link to navigate to Bob's profile
    await contactLink.click();
    await expect(authenticatedPage).toHaveURL(
      new RegExp(`/contacts/${bob.id}`)
    );

    // Verify we're now on Bob's detail page
    await expect(
      authenticatedPage.getByText(`${bob.firstName} ${bob.lastName}`).first()
    ).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Contact Management - Unauthenticated User', () => {
  test('should redirect to login when accessing contacts page unauthenticated', async ({
    unauthenticatedPage,
  }) => {
    await unauthenticatedPage.goto('/contacts');

    // Should be redirected to login page
    await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);

    // Should see login page content
    await expect(
      unauthenticatedPage.getByRole('heading', { name: 'Welcome Back' })
    ).toBeVisible({ timeout: 10000 });
  });

  test('should redirect to login when accessing create contact page unauthenticated', async ({
    unauthenticatedPage,
  }) => {
    await unauthenticatedPage.goto('/contacts/new');

    // Should be redirected to login page
    await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);

    // Should see login page content
    await expect(
      unauthenticatedPage.getByRole('heading', { name: 'Welcome Back' })
    ).toBeVisible({ timeout: 10000 });
  });

  test('should redirect to login when accessing contact details unauthenticated', async ({
    unauthenticatedPage,
  }) => {
    await unauthenticatedPage.goto('/contacts/123');

    // Should be redirected to login page
    await expect(unauthenticatedPage).toHaveURL(/\/auth\/login/);

    // Should see login page content
    await expect(
      unauthenticatedPage.getByRole('heading', { name: 'Welcome Back' })
    ).toBeVisible({ timeout: 10000 });
  });
});
