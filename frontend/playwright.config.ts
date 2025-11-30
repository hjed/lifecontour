import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E Test Configuration
 *
 * Configuration optimized for reliability following Playwright best practices:
 * - Web-first assertions with auto-retry
 * - Proper timeout configuration
 * - CI-specific settings for flaky test detection
 *
 * @see https://playwright.dev/docs/test-configuration
 * @see https://playwright.dev/docs/best-practices
 */
export default defineConfig({
  testDir: './tests/e2e',

  /* Global setup and teardown */
  globalSetup: './tests/global-setup.ts',
  globalTeardown: './tests/global-teardown.ts',

  /* Run tests in files in parallel */
  fullyParallel: true,

  /* Fail the build on CI if you accidentally left test.only in the source code */
  forbidOnly: !!process.env.CI,

  /* Fail on CI if any tests are marked as flaky - helps catch unreliable tests */
  failOnFlakyTests: !!process.env.CI,

  /* Retry failed tests to identify flaky tests vs genuine failures */
  retries: process.env.CI ? 2 : 0,

  /* Use single worker to prevent OAuth race conditions between parallel tests */
  workers: 1,

  /* Reporter configuration: GitHub annotations + HTML report on CI */
  reporter: process.env.CI ? [['github'], ['html']] : 'html',

  /* Global test timeout - generous but prevents hanging tests */
  timeout: 3 * 60 * 1000, // 3 minutes per test

  /* Global expect timeout - web-first assertions auto-retry until this timeout */
  expect: {
    timeout: 15000, // 15 seconds to account for network latency
  },

  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: 'http://localhost:3000',

    /* Collect trace on first retry - essential for debugging flaky tests */
    trace: 'on-first-retry',

    /* Set environment variables for tests */
    extraHTTPHeaders: {
      'X-Test-Backend-URL': 'http://localhost:8001',
    },

    /*
     * Action timeout - time to wait for individual actions (clicks, fills, etc.)
     * Playwright auto-waits for elements to be actionable before performing actions
     */
    actionTimeout: 20000, // 20 seconds

    /*
     * Navigation timeout - time to wait for page navigations
     * Should be generous to handle slow network conditions in CI
     */
    navigationTimeout: 60000, // 60 seconds

    /* Screenshot on failure for debugging */
    screenshot: 'only-on-failure',

    /* Video recording - only on failure in CI to save resources */
    video: process.env.CI ? 'retain-on-failure' : 'off',
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },

    {
      name: 'firefox',
      use: {
        ...devices['Desktop Firefox'],
        // Firefox-specific settings for better reliability
        launchOptions: {
          firefoxUserPrefs: {
            'dom.webnotifications.enabled': false,
            'dom.push.enabled': false,
          },
        },
        // Longer timeouts for Firefox
        actionTimeout: 15000,
        navigationTimeout: 45000,
      },
    },

    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
      // Note: WebKit has known issues with OAuth redirects in test environment
      // Tests may fail due to browser-specific JavaScript redirect handling
    },

    /* Test against mobile viewports. */
    {
      name: 'Mobile Chrome',
      use: { ...devices['Pixel 6'] },
    },
    {
      name: 'Mobile Safari',
      use: { ...devices['iPhone 12'] },
    },

    /* Test against branded browsers. */
    // {
    //   name: 'Microsoft Edge',
    //   use: { ...devices['Desktop Edge'], channel: 'msedge' },
    // },
    // {
    //   name: 'Google Chrome',
    //   use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    // },
  ],

  /* Run your local dev server before starting the tests */
  webServer: {
    command: 'pnpm dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000, // 2 minutes for dev server to start
    env: {
      BACKEND_URL: 'http://localhost:8001', // Use test backend port
      NEXT_PUBLIC_API_URL: 'http://localhost:8001',
      NEXT_PUBLIC_OAUTH_PROVIDER_URL: 'http://localhost:4446',
    },
  },
});
