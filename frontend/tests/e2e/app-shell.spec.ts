/**
 * End-to-end tests for the signed-in app shell: the header's user menu.
 */

import { test, expect } from './fixtures';
import {
  SOURCE_CODE_URL,
  THIRD_PARTY_NOTICES_PATH,
  UI_TEXT,
} from '../../src/lib/constants';

test.describe('User menu', () => {
  test('offers the source code and third-party notices', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await page.goto('/');

    const trigger = page.getByTestId('user-menu');
    await trigger.click();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');

    const menu = page.getByRole('menu');
    const sourceLink = menu.getByRole('menuitem', {
      name: UI_TEXT.SOURCE_CODE,
    });
    await expect(sourceLink).toHaveAttribute('href', SOURCE_CODE_URL);
    await expect(sourceLink).toHaveAttribute('target', '_blank');
    await expect(sourceLink).toHaveAttribute('rel', 'noopener noreferrer');

    const noticesLink = menu.getByRole('menuitem', {
      name: UI_TEXT.THIRD_PARTY_NOTICES,
    });
    await expect(noticesLink).toHaveAttribute('href', THIRD_PARTY_NOTICES_PATH);
    await expect(noticesLink).toHaveAttribute('target', '_blank');
    await expect(noticesLink).toHaveAttribute('rel', 'noopener noreferrer');
  });
});
