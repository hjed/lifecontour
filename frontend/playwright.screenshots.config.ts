import { defineConfig, devices } from '@playwright/test';
import e2eConfig from './playwright.config';

/**
 * README screenshot capture.
 *
 * Not a test suite: `tests/screenshots/` seeds fictional demo data on the
 * e2e stack and writes the images the README's Features section shows to
 * `docs/images/readme/`. Run it with `pnpm screenshots:readme` from
 * `frontend/`. CI never runs it — the main config's testDir is tests/e2e.
 *
 * It reuses the e2e config wholesale (global setup/teardown, web server,
 * timeouts) so the two can't drift, and swaps only the test directory and
 * projects.
 */

const AUTH_FILE = 'playwright/.auth/user.json';

export default defineConfig({
  ...e2eConfig,
  testDir: './tests/screenshots',
  testMatch: /.*\.screenshots\.ts/,
  retries: 0,
  reporter: 'list',
  projects: [
    // The OAuth setup lives with the e2e suite; point the project at it.
    {
      name: 'setup',
      testDir: './tests/e2e',
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: 'readme',
      use: {
        ...devices['Desktop Firefox'],
        viewport: { width: 1440, height: 900 },
        timezoneId: 'UTC',
        storageState: AUTH_FILE,
      },
      dependencies: ['setup'],
    },
  ],
});
