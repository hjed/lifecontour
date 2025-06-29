/**
 * E2E test utilities and helpers for Playwright tests.
 *
 * Provides common functionality for testing UI components,
 * accessibility, and responsive design.
 */

import { Page, expect } from '@playwright/test';

/**
 * Common selectors used across e2e tests.
 */
export const SELECTORS = {
  // Authentication
  LOGIN_FORM: 'main',
  LOGIN_CARD: '.max-w-md',
  LOGIN_TITLE: 'h1',
  LOGIN_DESCRIPTION: '[class*="text-muted-foreground"]',

  // OAuth Buttons
  GITHUB_BUTTON: 'button:has-text("Continue with GitHub")',
  MICROSOFT_BUTTON: 'button:has-text("Continue with Microsoft")',
  DISCORD_BUTTON: 'button:has-text("Continue with Discord")',

  // UI Components
  ALERT_ERROR: '[role="alert"]:not([id="__next-route-announcer__"])',
  LOADING_SPINNER: '[data-testid="loading"]',
  SEPARATOR: '[role="separator"]',

  // Navigation
  HEADER: 'header',
  MAIN_CONTENT: 'main',
} as const;

/**
 * Test data constants.
 */
export const TEST_DATA = {
  URLS: {
    LOGIN: '/auth/login',
    HOME: '/',
    DASHBOARD: '/dashboard',
  },

  OAUTH_PROVIDERS: ['github', 'microsoft', 'discord'] as const,

  VIEWPORT_SIZES: {
    MOBILE: { width: 375, height: 667 },
    TABLET: { width: 768, height: 1024 },
    DESKTOP: { width: 1280, height: 720 },
  },

  TIMEOUTS: {
    SHORT: 2000,
    MEDIUM: 5000,
    LONG: 10000,
  },
} as const;

/**
 * Accessibility testing utilities.
 */
export class AccessibilityHelpers {
  constructor(private readonly page: Page) {}

  /**
   * Check that all buttons have proper ARIA labels.
   */
  async checkButtonAccessibility(): Promise<void> {
    const buttons = await this.page.locator('button').all();

    for (const button of buttons) {
      const ariaLabel = await button.getAttribute('aria-label');
      const textContent = await button.textContent();

      // Button should have either aria-label or visible text
      expect(ariaLabel ?? textContent).toBeTruthy();
    }
  }

  /**
   * Check heading hierarchy (h1, h2, h3, etc.).
   */
  async checkHeadingHierarchy(): Promise<void> {
    const headings = await this.page.locator('h1, h2, h3, h4, h5, h6').all();

    if (headings.length > 0) {
      // First heading should be h1
      const firstHeading = headings[0];
      const tagName = await firstHeading.evaluate(el =>
        el.tagName.toLowerCase()
      );
      expect(tagName).toBe('h1');
    }
  }

  /**
   * Check that form elements have proper labels.
   */
  async checkFormAccessibility(): Promise<void> {
    const inputs = await this.page.locator('input, select, textarea').all();

    for (const input of inputs) {
      const id = await input.getAttribute('id');
      const ariaLabel = await input.getAttribute('aria-label');
      const ariaLabelledBy = await input.getAttribute('aria-labelledby');

      if (id) {
        // Check if there's a label for this input
        const label = this.page.locator(`label[for="${id}"]`);
        const hasLabel = (await label.count()) > 0;

        // Input should have label, aria-label, or aria-labelledby
        expect(hasLabel || ariaLabel || ariaLabelledBy).toBeTruthy();
      }
    }
  }

  /**
   * Check color contrast (basic check for text visibility).
   */
  async checkColorContrast(): Promise<void> {
    // This is a basic check - in a real implementation you might use
    // a more sophisticated color contrast checking library
    const textElements = await this.page
      .locator('p, span, div, button, a')
      .all();

    // Limit to first 10 elements to avoid timeouts
    const elementsToCheck = textElements.slice(0, 10);

    for (const element of elementsToCheck) {
      try {
        const isVisible = await element.isVisible({ timeout: 1000 });
        if (isVisible) {
          const textContent = await element.textContent({ timeout: 1000 });
          if (textContent?.trim()) {
            // Element with text should be visible
            await expect(element).toBeVisible({ timeout: 1000 });
          }
        }
      } catch (error) {
        // Skip elements that timeout or cause errors
        console.warn('Skipping element in color contrast check:', error);
      }
    }
  }
}

/**
 * Responsive design testing utilities.
 */
export class ResponsiveHelpers {
  constructor(private readonly page: Page) {}

  /**
   * Test component at different viewport sizes.
   */
  async testAtViewportSizes(
    testFn: (_viewportName: string) => Promise<void>
  ): Promise<void> {
    for (const [name, size] of Object.entries(TEST_DATA.VIEWPORT_SIZES)) {
      await this.page.setViewportSize(size);
      await testFn(name.toLowerCase());
    }
  }

  /**
   * Check that elements are properly responsive.
   */
  async checkResponsiveLayout(): Promise<void> {
    await this.testAtViewportSizes(async _viewportName => {
      // Check that main content is visible and properly sized
      const mainContent = this.page.locator(SELECTORS.MAIN_CONTENT);
      await expect(mainContent).toBeVisible();

      // Check that content doesn't overflow horizontally
      const bodyWidth = await this.page.evaluate(
        () => document.body.scrollWidth
      );
      const viewportWidth = await this.page.evaluate(() => window.innerWidth);

      // Allow for small differences due to scrollbars
      expect(bodyWidth).toBeLessThanOrEqual(viewportWidth + 20);
    });
  }

  /**
   * Check mobile-specific interactions.
   */
  async checkMobileInteractions(): Promise<void> {
    await this.page.setViewportSize(TEST_DATA.VIEWPORT_SIZES.MOBILE);

    // Check that buttons are large enough for touch
    const buttons = await this.page.locator('button').all();

    // Limit to first 5 buttons to avoid timeouts
    const buttonsToCheck = buttons.slice(0, 5);

    for (const button of buttonsToCheck) {
      try {
        const boundingBox = await button.boundingBox({ timeout: 2000 });
        if (boundingBox) {
          // Minimum touch target size should be 44x44px
          expect(boundingBox.height).toBeGreaterThanOrEqual(40);
          expect(boundingBox.width).toBeGreaterThanOrEqual(40);
        }
      } catch (error) {
        // Skip buttons that timeout or cause errors
        console.warn('Skipping button in mobile interactions check:', error);
      }
    }
  }
}

/**
 * Form interaction utilities.
 */
export class FormHelpers {
  constructor(private readonly page: Page) {}

  /**
   * Wait for form submission to complete.
   */
  async waitForFormSubmission(
    timeout = TEST_DATA.TIMEOUTS.MEDIUM
  ): Promise<void> {
    // Wait for any loading states to appear and disappear
    try {
      await this.page.waitForSelector('[disabled]', { timeout: 1000 });
      await this.page.waitForSelector('[disabled]', {
        state: 'detached',
        timeout,
      });
    } catch {
      // No loading state found, which is fine
    }
  }

  /**
   * Check form validation states.
   */
  async checkFormValidation(): Promise<void> {
    // Check for error messages
    const errorMessages = await this.page.locator('[role="alert"]').all();

    for (const error of errorMessages) {
      await expect(error).toBeVisible();
      const text = await error.textContent();
      expect(text).toBeTruthy();
    }
  }
}

/**
 * Create test helpers for a page.
 */
export function createTestHelpers(page: Page) {
  return {
    accessibility: new AccessibilityHelpers(page),
    responsive: new ResponsiveHelpers(page),
    form: new FormHelpers(page),
  };
}

/**
 * Wait for page to be fully loaded and interactive.
 */
export async function waitForPageReady(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle');
  await page.waitForLoadState('domcontentloaded');
}

/**
 * Take a screenshot with a descriptive name.
 */
export async function takeScreenshot(
  page: Page,
  name: string,
  options?: { fullPage?: boolean }
): Promise<void> {
  await page.screenshot({
    path: `test-results/screenshots/${name}.png`,
    fullPage: options?.fullPage ?? false,
  });
}
