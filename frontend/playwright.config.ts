import { defineConfig, devices } from '@playwright/test';

/**
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
  testDir: './tests/e2e',

  /* Global setup and teardown */
  globalSetup: './tests/global-setup.ts',
  globalTeardown: './tests/global-teardown.ts',

  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 1 : 0,
  /* Opt out of parallel tests on CI. */
  workers: 1, // Use single worker to prevent OAuth race conditions
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: process.env.CI ? [['github'], ['html']] : 'html',
  /* Global test timeout to prevent hanging tests */
  timeout: 3 * 60 * 1000, // 5 minutes per test

  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: 'http://localhost:3000',

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',

    /* Set environment variables for tests */
    extraHTTPHeaders: {
      'X-Test-Backend-URL': 'http://localhost:8001',
    },

    /* Increase timeout for better reliability */
    actionTimeout: 15000,
    navigationTimeout: 45000,

    /* Screenshot on failure for debugging */
    screenshot: 'only-on-failure',

    /* Video recording for CI */
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
