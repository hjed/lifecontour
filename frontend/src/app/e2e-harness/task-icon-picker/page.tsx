import { notFound } from 'next/navigation';
import { connection } from 'next/server';

import { TaskIconPickerHarness } from './TaskIconPickerHarness';

/**
 * Renders the icon picker on its own for the Playwright suite, before any
 * product page embeds it.
 *
 * Decided per request rather than at build time: CI's end-to-end server is a
 * production build, and only `playwright.config.ts` switches the flag on.
 */
export default async function TaskIconPickerHarnessPage() {
  await connection();
  if (process.env.E2E_TEST_ROUTES !== 'true') notFound();
  return <TaskIconPickerHarness />;
}
