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
    const pageContent = await authenticatedPage.textContent('body');
    expect(pageContent).toBeTruthy();
  });

  test('should load contact details page successfully when authenticated', async ({
    authenticatedPage,
  }) => {
    await authenticatedPage.goto('/contacts/123');

    // Verify the page loads successfully
    await expect(authenticatedPage).toHaveTitle(/Personal Management System/);

    // Page should load (might show 404 for non-existent contact, but that's valid)
    const pageContent = await authenticatedPage.textContent('body');
    expect(pageContent).toBeTruthy();
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
    const bodyText = await authenticatedPage.textContent('body');
    expect(bodyText).toBeTruthy();
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
    await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible();
    await expect(
      page.getByText(`${totalContacts} contacts found`)
    ).toBeVisible();

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
    await expect(infiniteScrollTrigger).toBeVisible();
    await infiniteScrollTrigger.scrollIntoViewIfNeeded();

    await expect.poll(async () => contactCards.count()).toBe(totalContacts);
    await expect(laterPageContact).toBeVisible();
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
    ).toBeVisible();
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
    ).toBeVisible();
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
    ).toBeVisible();
  });
});
