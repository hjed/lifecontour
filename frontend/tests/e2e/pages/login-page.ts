/**
 * Page object for authentication/login functionality.
 */

import { Page, expect } from '@playwright/test';
import { BasePage } from './base-page';

export class LoginPage extends BasePage {
  constructor(page: Page) {
    super(page);
  }

  // Selectors
  private readonly selectors = {
    loginButton: '[data-testid="login-button"]',
    providerButtons: '[data-testid^="oauth-provider-"]',
    githubProvider: '[data-testid="oauth-provider-github"]',
    microsoftProvider: '[data-testid="oauth-provider-microsoft"]',
    logoutButton: '[data-testid="logout-button"]',
    userMenu: '[data-testid="user-menu"]',
    userAvatar: '[data-testid="user-avatar"]',
    userName: '[data-testid="user-name"]',
    loginForm: '[data-testid="login-form"]',
    authError: '[data-testid="auth-error"]',
    authSuccess: '[data-testid="auth-success"]'
  };

  /**
   * Navigate to login page
   */
  async navigateToLogin() {
    await this.goto('/auth/login');
    await this.waitForLoad();
  }

  /**
   * Check if login form is visible
   */
  async isLoginFormVisible(): Promise<boolean> {
    return await this.isVisible(this.selectors.loginForm);
  }

  /**
   * Check if OAuth providers are displayed
   */
  async areOAuthProvidersVisible(): Promise<boolean> {
    return await this.isVisible(this.selectors.providerButtons);
  }

  /**
   * Get list of available OAuth providers
   */
  async getAvailableProviders(): Promise<string[]> {
    const providers = await this.page.locator(this.selectors.providerButtons).all();
    const providerNames: string[] = [];
    
    for (const provider of providers) {
      const testId = await provider.getAttribute('data-testid');
      if (testId) {
        const providerName = testId.replace('oauth-provider-', '');
        providerNames.push(providerName);
      }
    }
    
    return providerNames;
  }

  /**
   * Click on OAuth provider button
   */
  async clickOAuthProvider(provider: string) {
    const selector = `[data-testid="oauth-provider-${provider}"]`;
    await this.clickElement(selector);
  }

  /**
   * Simulate OAuth login flow
   * In real tests, this would redirect to OAuth provider
   * For e2e tests, we mock the successful return
   */
  async performOAuthLogin(provider: string = 'github') {
    await this.clickOAuthProvider(provider);
    
    // Wait for redirect to OAuth provider (mocked)
    await this.page.waitForURL('**/auth/callback**', { timeout: 5000 });
    
    // Simulate successful OAuth callback
    await this.page.goto('/auth/callback?code=test-auth-code&state=test-state');
    
    // Wait for redirect back to application
    await this.page.waitForURL('/', { timeout: 5000 });
  }

  /**
   * Check if user is logged in
   */
  async isUserLoggedIn(): Promise<boolean> {
    return await this.isVisible(this.selectors.userMenu) || 
           await this.isVisible(this.selectors.userAvatar);
  }

  /**
   * Get logged in user name
   */
  async getLoggedInUserName(): Promise<string> {
    if (await this.isVisible(this.selectors.userName)) {
      return await this.getTextContent(this.selectors.userName);
    }
    return '';
  }

  /**
   * Open user menu
   */
  async openUserMenu() {
    if (await this.isVisible(this.selectors.userMenu)) {
      await this.clickElement(this.selectors.userMenu);
    } else if (await this.isVisible(this.selectors.userAvatar)) {
      await this.clickElement(this.selectors.userAvatar);
    }
  }

  /**
   * Logout user
   */
  async logout() {
    await this.openUserMenu();
    await this.clickElement(this.selectors.logoutButton);
    
    // Wait for logout to complete
    await this.waitForApiResponse('**/api/auth/logout');
    
    // Should redirect to login or home page
    await this.page.waitForURL(/\/(auth\/login)?$/, { timeout: 5000 });
  }

  /**
   * Check for authentication error
   */
  async hasAuthError(): Promise<boolean> {
    return await this.isVisible(this.selectors.authError);
  }

  /**
   * Get authentication error message
   */
  async getAuthErrorMessage(): Promise<string> {
    return await this.getTextContent(this.selectors.authError);
  }

  /**
   * Check for authentication success message
   */
  async hasAuthSuccess(): Promise<boolean> {
    return await this.isVisible(this.selectors.authSuccess);
  }

  /**
   * Verify login page accessibility
   */
  async verifyLoginPageAccessibility() {
    await this.checkAccessibility();
    
    // Check specific login page accessibility requirements
    const loginButton = this.page.locator(this.selectors.loginButton);
    await expect(loginButton).toHaveAttribute('type', 'button');
    
    // Check OAuth provider buttons have proper labels
    const providerButtons = await this.page.locator(this.selectors.providerButtons).all();
    for (const button of providerButtons) {
      const ariaLabel = await button.getAttribute('aria-label');
      expect(ariaLabel).toBeTruthy();
    }
  }

  /**
   * Test responsive login form
   */
  async testResponsiveLogin() {
    // Test mobile layout
    await this.setViewportSize(BasePage.VIEWPORTS.MOBILE.width, BasePage.VIEWPORTS.MOBILE.height);
    await expect(this.page.locator(this.selectors.loginForm)).toBeVisible();
    
    // Test tablet layout
    await this.setViewportSize(BasePage.VIEWPORTS.TABLET.width, BasePage.VIEWPORTS.TABLET.height);
    await expect(this.page.locator(this.selectors.loginForm)).toBeVisible();
    
    // Test desktop layout
    await this.setViewportSize(BasePage.VIEWPORTS.DESKTOP.width, BasePage.VIEWPORTS.DESKTOP.height);
    await expect(this.page.locator(this.selectors.loginForm)).toBeVisible();
  }

  /**
   * Verify protected route redirection
   */
  async verifyProtectedRouteRedirection(protectedPath: string) {
    // Try to access protected route without authentication
    await this.goto(protectedPath);
    
    // Should be redirected to login
    await this.page.waitForURL('**/auth/login**', { timeout: 5000 });
    
    // Verify login form is shown
    await expect(this.page.locator(this.selectors.loginForm)).toBeVisible();
  }

  /**
   * Verify session persistence
   */
  async verifySessionPersistence() {
    // Refresh the page
    await this.page.reload();
    await this.waitForLoad();
    
    // User should still be logged in
    expect(await this.isUserLoggedIn()).toBe(true);
  }
}
