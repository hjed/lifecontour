/**
 * End-to-end tests for responsive design and mobile functionality.
 * 
 * Tests mobile-first approach, responsive layouts, and touch interactions.
 * These tests define the expected behavior for ITER1-004 responsive UI.
 */

import { test, expect } from '@playwright/test';
import { LoginPage } from './pages/login-page';
import { ContactsPage } from './pages/contacts-page';
import { ContactFormPage } from './pages/contact-form-page';
import { setupApiMocks } from './utils/api-mocks';

test.describe('Responsive Design', () => {
  let loginPage: LoginPage;
  let contactsPage: ContactsPage;
  let contactFormPage: ContactFormPage;

  // Common viewport sizes for testing
  const viewports = {
    mobile: { width: 375, height: 667 }, // iPhone SE
    mobileLarge: { width: 414, height: 896 }, // iPhone 11 Pro Max
    tablet: { width: 768, height: 1024 }, // iPad
    tabletLarge: { width: 1024, height: 768 }, // iPad landscape
    desktop: { width: 1920, height: 1080 }, // Desktop
    desktopLarge: { width: 2560, height: 1440 } // Large desktop
  };

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    contactsPage = new ContactsPage(page);
    contactFormPage = new ContactFormPage(page);
    
    // Set up API mocks for consistent testing
    await setupApiMocks(page);
    
    // Login before each test
    await loginPage.navigateToLogin();
    await loginPage.performOAuthLogin('github');
  });

  test('should display mobile navigation correctly', async ({ page }) => {
    // Test mobile viewport
    await page.setViewportSize(viewports.mobile);
    await page.goto('/');
    
    // Mobile menu button should be visible
    expect(await page.isVisible('[data-testid="mobile-menu-button"]')).toBe(true);
    
    // Desktop navigation should be hidden
    expect(await page.isVisible('[data-testid="desktop-navigation"]')).toBe(false);
    
    // Open mobile menu
    await page.click('[data-testid="mobile-menu-button"]');
    
    // Mobile menu should be visible
    expect(await page.isVisible('[data-testid="mobile-menu"]')).toBe(true);
    
    // Navigation links should be accessible
    expect(await page.isVisible('[data-testid="nav-contacts"]')).toBe(true);
    expect(await page.isVisible('[data-testid="nav-search"]')).toBe(true);
  });

  test('should display desktop navigation correctly', async ({ page }) => {
    // Test desktop viewport
    await page.setViewportSize(viewports.desktop);
    await page.goto('/');
    
    // Desktop navigation should be visible
    expect(await page.isVisible('[data-testid="desktop-navigation"]')).toBe(true);
    
    // Mobile menu button should be hidden
    expect(await page.isVisible('[data-testid="mobile-menu-button"]')).toBe(false);
    
    // Navigation links should be directly accessible
    expect(await page.isVisible('[data-testid="nav-contacts"]')).toBe(true);
    expect(await page.isVisible('[data-testid="nav-search"]')).toBe(true);
  });

  test('should adapt contacts list layout for different screen sizes', async ({ page }) => {
    await contactsPage.navigateToContacts();
    
    // Test mobile layout
    await page.setViewportSize(viewports.mobile);
    
    // Contacts should be displayed in a single column
    const mobileContactsList = page.locator('[data-testid="contacts-list"]');
    expect(await mobileContactsList.isVisible()).toBe(true);
    
    // Contact cards should stack vertically
    const mobileContactItems = await page.locator('[data-testid^="contact-item-"]').all();
    if (mobileContactItems.length >= 2) {
      const firstItemBox = await mobileContactItems[0].boundingBox();
      const secondItemBox = await mobileContactItems[1].boundingBox();
      
      // Second item should be below first item (stacked)
      expect(secondItemBox?.y).toBeGreaterThan(firstItemBox?.y! + firstItemBox?.height!);
    }
    
    // Test tablet layout
    await page.setViewportSize(viewports.tablet);
    
    // Contacts list should adapt to tablet layout
    expect(await mobileContactsList.isVisible()).toBe(true);
    
    // Test desktop layout
    await page.setViewportSize(viewports.desktop);
    
    // Desktop layout might show more columns or different arrangement
    expect(await mobileContactsList.isVisible()).toBe(true);
  });

  test('should make contact forms usable on mobile', async ({ page }) => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();
    
    // Test mobile form layout
    await page.setViewportSize(viewports.mobile);
    
    // Form should be visible and usable
    expect(await contactFormPage.isContactFormVisible()).toBe(true);
    
    // Form fields should be properly sized for mobile
    const firstNameInput = page.locator('[data-testid="first-name-input"]');
    const inputBox = await firstNameInput.boundingBox();
    
    // Input should not be wider than viewport
    expect(inputBox?.width).toBeLessThanOrEqual(viewports.mobile.width);
    
    // Test form interaction on mobile
    await page.fill('[data-testid="first-name-input"]', 'Mobile');
    await page.fill('[data-testid="last-name-input"]', 'User');
    await page.fill('[data-testid="email-input"]', 'mobile@example.com');
    
    // Form should be submittable on mobile
    await contactFormPage.saveContact();
    
    // Should redirect to contacts list
    expect(await contactsPage.isContactsListVisible()).toBe(true);
  });

  test('should make search functionality work on mobile', async ({ page }) => {
    await page.setViewportSize(viewports.mobile);
    await page.goto('/');
    
    // Global search should be accessible on mobile
    const searchInput = page.locator('[data-testid="global-search-input"]');
    expect(await searchInput.isVisible()).toBe(true);
    
    // Search input should be appropriately sized
    const searchBox = await searchInput.boundingBox();
    expect(searchBox?.width).toBeLessThanOrEqual(viewports.mobile.width - 40); // Account for padding
    
    // Test search on mobile
    await page.fill('[data-testid="global-search-input"]', 'john');
    await page.click('[data-testid="global-search-button"]');
    
    // Wait for search results
    await page.waitForResponse('**/api/search/global**');
    
    // Search results should be displayed properly on mobile
    const searchResults = page.locator('[data-testid="global-search-results"]');
    expect(await searchResults.isVisible()).toBe(true);
    
    // Results should not overflow viewport
    const resultsBox = await searchResults.boundingBox();
    expect(resultsBox?.width).toBeLessThanOrEqual(viewports.mobile.width);
  });

  test('should support touch interactions on mobile', async ({ page }) => {
    await page.setViewportSize(viewports.mobile);
    await contactsPage.navigateToContacts();
    
    // Test touch tap on contact item
    const firstContact = page.locator('[data-testid^="contact-item-"]:first-child');
    
    // Simulate touch tap
    await firstContact.tap();
    
    // Should respond to touch interaction
    // Behavior depends on implementation (might open contact details or select)
    
    // Test touch on mobile menu
    await page.tap('[data-testid="mobile-menu-button"]');
    
    // Mobile menu should open
    expect(await page.isVisible('[data-testid="mobile-menu"]')).toBe(true);
    
    // Test touch on navigation link
    await page.tap('[data-testid="nav-contacts"]');
    
    // Should navigate properly
    expect(await contactsPage.isContactsListVisible()).toBe(true);
  });

  test('should handle orientation changes', async ({ page }) => {
    // Start in portrait mobile
    await page.setViewportSize(viewports.mobile);
    await contactsPage.navigateToContacts();
    
    // Verify portrait layout
    expect(await contactsPage.isContactsListVisible()).toBe(true);
    
    // Switch to landscape mobile
    await page.setViewportSize({ width: 667, height: 375 });
    
    // Layout should adapt to landscape
    expect(await contactsPage.isContactsListVisible()).toBe(true);
    
    // Navigation should still work
    expect(await page.isVisible('[data-testid="mobile-menu-button"]')).toBe(true);
  });

  test('should scale properly across all viewport sizes', async ({ page }) => {
    await page.goto('/');
    
    // Test each viewport size
    for (const [name, viewport] of Object.entries(viewports)) {
      await page.setViewportSize(viewport);
      
      // Page should be usable at this size
      expect(await page.isVisible('body')).toBe(true);
      
      // No horizontal scrolling should be needed
      const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
      expect(bodyWidth).toBeLessThanOrEqual(viewport.width + 1); // Allow 1px tolerance
      
      // Navigation should be appropriate for screen size
      if (viewport.width < 768) {
        // Mobile navigation
        expect(await page.isVisible('[data-testid="mobile-menu-button"]')).toBe(true);
      } else {
        // Desktop navigation
        expect(await page.isVisible('[data-testid="desktop-navigation"]')).toBe(true);
      }
    }
  });

  test('should maintain accessibility on mobile', async ({ page }) => {
    await page.setViewportSize(viewports.mobile);
    await page.goto('/');
    
    // Touch targets should be large enough (minimum 44px)
    const touchTargets = await page.locator('button, a, [role="button"]').all();
    
    for (const target of touchTargets) {
      const box = await target.boundingBox();
      if (box) {
        // Touch targets should be at least 44px in both dimensions
        expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(44);
      }
    }
    
    // Text should be readable (minimum 16px on mobile)
    const textElements = await page.locator('p, span, div').all();
    
    for (const element of textElements.slice(0, 5)) { // Test first 5 elements
      const fontSize = await element.evaluate(el => 
        window.getComputedStyle(el).fontSize
      );
      const fontSizeNum = parseInt(fontSize.replace('px', ''));
      expect(fontSizeNum).toBeGreaterThanOrEqual(14); // Allow slightly smaller for mobile
    }
  });

  test('should handle long content gracefully on mobile', async ({ page }) => {
    await page.setViewportSize(viewports.mobile);
    
    // Mock contact with very long content
    await page.route('**/api/contacts**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: [{
            type: 'contact',
            id: '1',
            attributes: {
              first_name: 'VeryLongFirstNameThatShouldWrapProperly',
              last_name: 'VeryLongLastNameThatShouldAlsoWrapProperly',
              email: 'very.long.email.address.that.should.wrap@example.com',
              company: 'Very Long Company Name That Should Wrap Properly On Mobile Devices',
              notes: 'This is a very long note that should wrap properly on mobile devices without causing horizontal scrolling or layout issues.',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z'
            }
          }],
          meta: { total: 1, page: 1, limit: 20, total_pages: 1 },
          links: {}
        })
      });
    });

    await contactsPage.navigateToContacts();
    
    // Long content should wrap and not cause horizontal scrolling
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(viewports.mobile.width + 1);
    
    // Contact information should still be readable
    expect(await contactsPage.isContactsListVisible()).toBe(true);
  });

  test('should optimize performance on mobile', async ({ page }) => {
    await page.setViewportSize(viewports.mobile);
    
    // Measure page load time
    const startTime = Date.now();
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    const loadTime = Date.now() - startTime;
    
    // Page should load reasonably quickly on mobile
    expect(loadTime).toBeLessThan(5000); // 5 seconds max
    
    // Images should be optimized for mobile
    const images = await page.locator('img').all();
    for (const img of images) {
      const src = await img.getAttribute('src');
      if (src) {
        // Should use appropriate image sizes for mobile
        // This would depend on implementation details
      }
    }
  });
});
