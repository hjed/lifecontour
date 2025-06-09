/**
 * Simple test to verify Playwright setup is working correctly.
 * This test validates our test infrastructure before running the main ITER1-004 tests.
 */

import { test, expect } from '@playwright/test';
import { setupApiMocks } from './utils/api-mocks';
import { LoginPage } from './pages/login-page';
import { ContactsPage } from './pages/contacts-page';
import { ContactFormPage } from './pages/contact-form-page';

test.describe('Test Setup Verification', () => {
  test('should verify API mocking works correctly', async ({ page }) => {
    // Set up API mocks
    await setupApiMocks(page);
    
    // Test that our mock endpoints respond correctly
    const response = await page.request.get('http://localhost:8000/api/health');
    expect(response.ok()).toBe(true);
    
    const healthData = await response.json();
    expect(healthData.status).toBe('healthy');
  });

  test('should verify test data fixtures are accessible', async () => {
    const { testContacts, testUser } = await import('./fixtures/test-data');
    
    // Verify test contacts are properly structured
    expect(testContacts).toBeDefined();
    expect(testContacts.length).toBeGreaterThan(0);
    expect(testContacts[0]).toHaveProperty('firstName');
    expect(testContacts[0]).toHaveProperty('lastName');
    
    // Verify test user is properly structured
    expect(testUser).toBeDefined();
    expect(testUser).toHaveProperty('id');
    expect(testUser).toHaveProperty('email');
  });

  test('should verify page objects can be instantiated', async ({ page }) => {
    // Verify page objects can be created
    const loginPage = new LoginPage(page);
    const contactsPage = new ContactsPage(page);
    const contactFormPage = new ContactFormPage(page);

    expect(loginPage).toBeDefined();
    expect(contactsPage).toBeDefined();
    expect(contactFormPage).toBeDefined();
  });

  test('should verify Australian locale settings', async ({ page }) => {
    // Check that the page uses Australian locale
    const locale = await page.evaluate(() => navigator.language);
    console.log('Browser locale:', locale);
    
    // Check timezone (this might not work in headless mode)
    const timezone = await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
    console.log('Browser timezone:', timezone);
    
    // Test Australian date formatting
    const testDate = new Date('2024-01-15');
    const formattedDate = testDate.toLocaleDateString('en-AU');
    expect(formattedDate).toBe('15/01/2024');
  });

  test('should verify responsive viewport testing works', async ({ page }) => {
    // Test different viewport sizes
    const viewports = [
      { width: 375, height: 667, name: 'mobile' },
      { width: 768, height: 1024, name: 'tablet' },
      { width: 1920, height: 1080, name: 'desktop' }
    ];

    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      
      const actualViewport = page.viewportSize();
      expect(actualViewport?.width).toBe(viewport.width);
      expect(actualViewport?.height).toBe(viewport.height);
    }
  });

  test('should verify error handling works', async ({ page }) => {
    // Test that we can catch and handle errors properly
    let errorCaught = false;
    
    try {
      await page.goto('http://invalid-url-that-should-fail');
    } catch (error) {
      errorCaught = true;
      expect(error).toBeDefined();
    }
    
    expect(errorCaught).toBe(true);
  });
});
