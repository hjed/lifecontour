/**
 * Base page object for common functionality across all pages.
 */

import { Page, expect } from '@playwright/test';

export class BasePage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  /**
   * Navigate to a specific path
   */
  async goto(path: string = '/') {
    await this.page.goto(path);
  }

  /**
   * Wait for page to be loaded
   */
  async waitForLoad() {
    await this.page.waitForLoadState('networkidle');
  }

  /**
   * Get page title
   */
  async getTitle(): Promise<string> {
    return await this.page.title();
  }

  /**
   * Check if element is visible
   */
  async isVisible(selector: string): Promise<boolean> {
    return await this.page.isVisible(selector);
  }

  /**
   * Wait for element to be visible
   */
  async waitForSelector(selector: string, timeout: number = 5000) {
    await this.page.waitForSelector(selector, { timeout });
  }

  /**
   * Click element with retry logic
   */
  async clickElement(selector: string) {
    await this.page.click(selector);
  }

  /**
   * Fill input field
   */
  async fillInput(selector: string, value: string) {
    await this.page.fill(selector, value);
  }

  /**
   * Get text content of element
   */
  async getTextContent(selector: string): Promise<string> {
    const element = await this.page.locator(selector);
    return (await element.textContent()) || '';
  }

  /**
   * Wait for API response
   */
  async waitForApiResponse(
    urlPattern: string | RegExp,
    timeout: number = 10000
  ) {
    return await this.page.waitForResponse(urlPattern, { timeout });
  }

  /**
   * Check for error messages
   */
  async hasErrorMessage(): Promise<boolean> {
    return await this.isVisible('[data-testid="error-message"]');
  }

  /**
   * Get error message text
   */
  async getErrorMessage(): Promise<string> {
    return await this.getTextContent('[data-testid="error-message"]');
  }

  /**
   * Check for success messages
   */
  async hasSuccessMessage(): Promise<boolean> {
    return await this.isVisible('[data-testid="success-message"]');
  }

  /**
   * Get success message text
   */
  async getSuccessMessage(): Promise<string> {
    return await this.getTextContent('[data-testid="success-message"]');
  }

  /**
   * Check for loading states
   */
  async isLoading(): Promise<boolean> {
    return await this.isVisible('[data-testid="loading-spinner"]');
  }

  /**
   * Wait for loading to complete
   */
  async waitForLoadingToComplete() {
    await this.page.waitForSelector('[data-testid="loading-spinner"]', {
      state: 'hidden',
      timeout: 10000,
    });
  }

  /**
   * Take screenshot for debugging
   */
  async takeScreenshot(name: string) {
    await this.page.screenshot({
      path: `test-results/screenshots/${name}.png`,
      fullPage: true,
    });
  }

  /**
   * Check responsive design by changing viewport
   */
  async setViewportSize(width: number, height: number) {
    await this.page.setViewportSize({ width, height });
  }

  /**
   * Common viewport sizes for testing
   */
  static readonly VIEWPORTS = {
    MOBILE: { width: 375, height: 667 },
    TABLET: { width: 768, height: 1024 },
    DESKTOP: { width: 1920, height: 1080 },
  };

  /**
   * Check if navigation menu is visible (for responsive testing)
   */
  async hasNavigationMenu(): Promise<boolean> {
    return await this.isVisible('[data-testid="navigation-menu"]');
  }

  /**
   * Check if mobile hamburger menu is visible
   */
  async hasMobileMenu(): Promise<boolean> {
    return await this.isVisible('[data-testid="mobile-menu-button"]');
  }

  /**
   * Open mobile menu
   */
  async openMobileMenu() {
    if (await this.hasMobileMenu()) {
      await this.clickElement('[data-testid="mobile-menu-button"]');
    }
  }

  /**
   * Verify Australian date format (DD/MM/YYYY)
   */
  async verifyAustralianDateFormat(selector: string, expectedDate: Date) {
    const dateText = await this.getTextContent(selector);
    const expectedFormat = expectedDate.toLocaleDateString('en-AU');
    expect(dateText).toContain(expectedFormat);
  }

  /**
   * Common assertions for accessibility
   */
  async checkAccessibility() {
    // Check for proper heading structure
    const h1Count = await this.page.locator('h1').count();
    expect(h1Count).toBeGreaterThanOrEqual(1);

    // Check for alt text on images
    const images = await this.page.locator('img').all();
    for (const img of images) {
      const alt = await img.getAttribute('alt');
      expect(alt).toBeTruthy();
    }

    // Check for form labels
    const inputs = await this.page
      .locator('input[type="text"], input[type="email"], textarea')
      .all();
    for (const input of inputs) {
      const id = await input.getAttribute('id');
      if (id) {
        const label = await this.page.locator(`label[for="${id}"]`).count();
        expect(label).toBeGreaterThan(0);
      }
    }
  }
}
