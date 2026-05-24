import { defineConfig, devices } from '@playwright/test';
import {
  FRONTEND_TEST_PORT,
  FRONTEND_TEST_URL,
  SHOULD_REUSE_PLAYWRIGHT_WEB_SERVER,
  BACKEND_TEST_PORT,
  OAUTH_PUBLIC_TEST_PORT,
} from './tests/e2e/utils/frontend-test-config';

/**
 * Playwright E2E Test Configuration
 *
 * Uses Playwright's setup project pattern for authentication:
 * 1. The 'setup' project runs first, performs OAuth once, saves storageState
 * 2. All browser projects depend on 'setup' and load the saved auth state
 * 3. Every test starts pre-authenticated — no per-test OAuth overhead
 *
 * @see https://playwright.dev/docs/auth
 * @see https://playwright.dev/docs/test-configuration
 */

const AUTH_FILE = 'playwright/.auth/user.json';

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

  /* Reporter configuration: GitHub annotations + HTML report on CI, list reporter locally */
  reporter: process.env.CI ? [['github'], ['html']] : 'list',

  /* Global test timeout - generous but prevents hanging tests */
  timeout: 3 * 60 * 1000, // 3 minutes per test

  /* Global expect timeout - web-first assertions auto-retry until this timeout */
  expect: {
    timeout: 15000, // 15 seconds to account for network latency
  },

  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: FRONTEND_TEST_URL,

    /* Collect trace on first retry - essential for debugging flaky tests */
    trace: 'on-first-retry',

    /* Set environment variables for tests */
    extraHTTPHeaders: {
      'X-Test-Backend-URL': `http://localhost:${BACKEND_TEST_PORT}`,
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

    /*
     * Disable CSS animations/transitions during tests.
     * The popover open animations (fade-in, zoom-in, slide-in from tw-animate-css)
     * cause calendar buttons to be perpetually "not stable" in Playwright's
     * actionability checks, leading to consistent click timeouts.
     */
    contextOptions: {
      reducedMotion: 'reduce',
    },
  },

  /* Configure projects for major browsers */
  /* Only test browsers that are tested in CI: chromium, firefox, and Mobile Chrome */
  /* Note: Webkit (Safari) was removed due to known issues with OAuth redirects in test environments */
  projects: [
    // Setup project: performs OAuth once and saves storageState
    {
      name: 'setup',
      testMatch: /.*\.setup\.ts/,
    },

    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        timezoneId: 'UTC',
        storageState: AUTH_FILE,
      },
      dependencies: ['setup'],
    },

    {
      name: 'firefox',
      use: {
        ...devices['Desktop Firefox'],
        timezoneId: 'UTC',
        storageState: AUTH_FILE,
        // Firefox-specific settings for better reliability
        launchOptions: {
          firefoxUserPrefs: {
            'dom.webnotifications.enabled': false,
            'dom.push.enabled': false,
          },
        },
        // Firefox inherits global actionTimeout (20s) and navigationTimeout (60s)
        // which are more generous than the previously set Firefox-specific values
      },
      dependencies: ['setup'],
    },

    /* Test against mobile viewports. */
    {
      name: 'Mobile Chrome',
      use: {
        ...devices['Pixel 7'],
        timezoneId: 'UTC',
        storageState: AUTH_FILE,
        // Mobile viewport interactions (hamburger menus, touch targets) need
        // slightly longer action timeouts than desktop browsers.
        // Decouple from global retries to prevent worker OAuth retry cascades
        actionTimeout: 30000,
      },
      dependencies: ['setup'],
      retries: 0,
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
    url: FRONTEND_TEST_URL,
    // Default to a fresh repo-controlled frontend server for deterministic local runs.
    reuseExistingServer: SHOULD_REUSE_PLAYWRIGHT_WEB_SERVER,
    timeout: 120 * 1000, // 2 minutes for dev server to start
    stdout: 'ignore', // Suppress dev server output to avoid cluttering test output
    stderr: 'pipe', // Show errors from dev server
    env: {
      ...process.env,
      PORT: FRONTEND_TEST_PORT,
      BACKEND_URL: `http://localhost:${BACKEND_TEST_PORT}`, // Use test backend port
      NEXT_PUBLIC_API_URL: `http://localhost:${BACKEND_TEST_PORT}`,
      NEXT_PUBLIC_OAUTH_PROVIDER_URL: `http://localhost:${OAUTH_PUBLIC_TEST_PORT}`,
    },
  },
});
