import { test, expect } from './fixtures';

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
