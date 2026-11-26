/**
 * The icon picker's end-to-end harness exists only for the Playwright server.
 *
 * It answers 404 unless the server runs with `E2E_TEST_ROUTES=true`, which
 * only `playwright.config.ts` sets, so no deployment serves a test page.
 */

import { render, screen } from '@testing-library/react';

import TaskIconPickerHarnessPage from '@/app/e2e-harness/task-icon-picker/page';

const NOT_FOUND = new Error('NEXT_NOT_FOUND');

jest.mock('next/navigation', () => ({
  notFound: () => {
    throw NOT_FOUND;
  },
}));

jest.mock('next/server', () => ({
  connection: () => Promise.resolve(),
}));

describe('the icon picker harness page', () => {
  const original = process.env.E2E_TEST_ROUTES;

  afterEach(() => {
    if (original === undefined) delete process.env.E2E_TEST_ROUTES;
    else process.env.E2E_TEST_ROUTES = original;
  });

  it('is not found when test routes are not switched on', async () => {
    delete process.env.E2E_TEST_ROUTES;

    await expect(TaskIconPickerHarnessPage()).rejects.toBe(NOT_FOUND);
  });

  it('is not found for any value but "true"', async () => {
    process.env.E2E_TEST_ROUTES = 'false';

    await expect(TaskIconPickerHarnessPage()).rejects.toBe(NOT_FOUND);
  });

  it('renders the picker and the value it hands back when switched on', async () => {
    process.env.E2E_TEST_ROUTES = 'true';

    render(await TaskIconPickerHarnessPage());

    expect(
      screen.getByRole('radiogroup', { name: 'Icon' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('status', { name: 'Chosen icon value' })
    ).toHaveTextContent('none');
  });
});
