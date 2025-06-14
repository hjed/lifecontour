import { test, expect } from '@playwright/test';
import { createAuthFixtures } from './fixtures/auth';

test.describe('Contact Management', () => {
  test.beforeEach(async ({ page }) => {
    // Authenticate user before each test
    const authFixtures = createAuthFixtures(page);
    await authFixtures.mockAuthenticated('github');
  });

  test('should display contacts page with header and navigation', async ({
    page,
  }) => {
    // Mock empty contacts response
    await page.route('/api/contacts*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: [],
          meta: { total: 0, page: 1, per_page: 20, total_pages: 0 },
        }),
      });
    });

    await page.goto('/contacts');

    // Check page title and header (should contain the site title)
    await expect(page).toHaveTitle(/Personal Management System/);
    await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible();
    await expect(
      page.getByText('Manage your personal and professional contacts')
    ).toBeVisible();

    // Check navigation elements
    await expect(
      page.getByRole('link', { name: /add contact/i })
    ).toBeVisible();
    await expect(page.getByPlaceholder('Search contacts...')).toBeVisible();
    await expect(page.getByRole('button', { name: /filters/i })).toBeVisible();
  });

  test('should show and hide filter panel', async ({ page }) => {
    // Mock empty contacts response
    await page.route('/api/contacts*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: [],
          meta: { total: 0, page: 1, per_page: 20, total_pages: 0 },
        }),
      });
    });

    await page.goto('/contacts');

    const filtersButton = page.getByRole('button', { name: /filters/i });

    // Filter panel should not be visible initially
    await expect(
      page.getByText('Filter by tags (coming soon)')
    ).not.toBeVisible();

    // Click to show filters
    await filtersButton.click();
    await expect(page.getByText('Filter by tags (coming soon)')).toBeVisible();
    await expect(page.getByText('Filter by date (coming soon)')).toBeVisible();

    // Click again to hide filters
    await filtersButton.click();
    await expect(
      page.getByText('Filter by tags (coming soon)')
    ).not.toBeVisible();
  });

  test('should handle search functionality', async ({ page }) => {
    await page.goto('/contacts');

    const searchInput = page.getByPlaceholder('Search contacts...');

    // Type in search
    await searchInput.fill('John');
    await expect(searchInput).toHaveValue('John');

    // Clear button should appear
    await expect(page.getByRole('button', { name: /clear/i })).toBeVisible();

    // Click clear
    await page.getByRole('button', { name: /clear/i }).click();
    await expect(searchInput).toHaveValue('');
    await expect(
      page.getByRole('button', { name: /clear/i })
    ).not.toBeVisible();
  });

  test('should navigate to create contact page', async ({ page }) => {
    await page.goto('/contacts');

    // Click add contact button
    await page.getByRole('button', { name: /add contact/i }).click();

    // Should navigate to new contact page
    await expect(page).toHaveURL('/contacts/new');
    await expect(
      page.getByRole('heading', { name: 'Add New Contact' })
    ).toBeVisible();
    await expect(
      page.getByText('Create a new contact with their information and details')
    ).toBeVisible();
  });

  test('should create a new contact', async ({ page }) => {
    await page.goto('/contacts/new');

    // Fill in the form
    await page.getByLabel(/first name/i).fill('Jane');
    await page.getByLabel(/last name/i).fill('Smith');
    await page.getByLabel(/middle name/i).fill('Marie');
    await page.getByLabel(/nickname/i).fill('Janie');

    // Submit the form
    await page.getByRole('button', { name: /save contact/i }).click();

    // Should show loading state
    await expect(page.getByRole('button', { name: /saving/i })).toBeVisible();

    // Should navigate to contact detail page (mocked response)
    // Note: In a real test, this would depend on the backend response
    // For now, we'll just check that the form submission was attempted
  });

  test('should validate required fields on contact creation', async ({
    page,
  }) => {
    await page.goto('/contacts/new');

    // Try to submit without filling required fields
    await page.getByRole('button', { name: /save contact/i }).click();

    // Should show validation error
    await expect(page.getByText(/this field is required/i)).toBeVisible();
  });

  test('should navigate back from create contact page', async ({ page }) => {
    await page.goto('/contacts/new');

    // Click back button
    await page.getByRole('button', { name: /back to contacts/i }).click();

    // Should navigate back to contacts list
    await expect(page).toHaveURL('/contacts');
  });

  test('should cancel contact creation', async ({ page }) => {
    await page.goto('/contacts/new');

    // Fill in some data
    await page.getByLabel(/first name/i).fill('Test');

    // Click cancel
    await page.getByRole('button', { name: /cancel/i }).click();

    // Should navigate back to contacts list
    await expect(page).toHaveURL('/contacts');
  });

  test('should display empty state when no contacts', async ({ page }) => {
    // Mock empty response
    await page.route('/api/contacts*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: [],
          meta: { total: 0, page: 1, per_page: 20, total_pages: 0 },
        }),
      });
    });

    await page.goto('/contacts');

    // Should show empty state
    await expect(page.getByText('No contacts found')).toBeVisible();
    await expect(
      page.getByText('Get started by adding your first contact')
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: /add contact/i })
    ).toBeVisible();
  });

  test('should display contacts list', async ({ page }) => {
    // Mock contacts response
    await page.route('/api/contacts*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: [
            {
              id: '1',
              type: 'contacts',
              attributes: {
                first_name: 'John',
                last_name: 'Doe',
                middle_name: '',
                nick_name: '',
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
                contact_methods: [
                  {
                    id: 1,
                    attributes: {
                      method_type: 'email',
                      value: 'john@example.com',
                      label: 'Work',
                      is_primary: true,
                    },
                  },
                ],
                addresses: [],
                notes: [],
              },
              relationships: {
                tags: { data: [] },
              },
            },
          ],
          meta: { total: 1, page: 1, per_page: 20, total_pages: 1 },
        }),
      });
    });

    await page.goto('/contacts');

    // Should display contact
    await expect(page.getByText('John Doe')).toBeVisible();
    await expect(page.getByText('Email: john@example.com')).toBeVisible();
    await expect(page.getByText('1 contact found')).toBeVisible();
  });

  test('should navigate to contact detail page', async ({ page }) => {
    // Mock contacts response
    await page.route('/api/contacts*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: [
            {
              id: '1',
              type: 'contacts',
              attributes: {
                first_name: 'John',
                last_name: 'Doe',
                middle_name: '',
                nick_name: '',
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
                contact_methods: [],
                addresses: [],
                notes: [],
              },
              relationships: {
                tags: { data: [] },
              },
            },
          ],
          meta: { total: 1, page: 1, per_page: 20, total_pages: 1 },
        }),
      });
    });

    // Mock individual contact response
    await page.route('/api/contacts/1', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            id: '1',
            type: 'contacts',
            attributes: {
              first_name: 'John',
              last_name: 'Doe',
              middle_name: '',
              nick_name: '',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z',
              contact_methods: [],
              addresses: [],
              notes: [],
            },
            relationships: {
              tags: { data: [] },
            },
          },
        }),
      });
    });

    await page.goto('/contacts');

    // Click on contact name
    await page.getByText('John Doe').click();

    // Should navigate to contact detail page
    await expect(page).toHaveURL('/contacts/1');
    await expect(page.getByRole('heading', { name: 'John Doe' })).toBeVisible();
  });

  test('should be responsive on mobile', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });

    await page.goto('/contacts');

    // Check that mobile layout is working
    await expect(page.getByRole('heading', { name: 'Contacts' })).toBeVisible();
    await expect(
      page.getByRole('button', { name: /add contact/i })
    ).toBeVisible();
    await expect(page.getByPlaceholder('Search contacts...')).toBeVisible();

    // Filter button should be visible on mobile
    await expect(page.getByRole('button', { name: /filters/i })).toBeVisible();
  });

  test('should handle API errors gracefully', async ({ page }) => {
    // Mock error response
    await page.route('/api/contacts*', async route => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          errors: [{ detail: 'Internal server error' }],
        }),
      });
    });

    await page.goto('/contacts');

    // Should show error message
    await expect(page.getByText(/failed to load contacts/i)).toBeVisible();
  });
});
