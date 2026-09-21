import { expect, type Locator, type Page } from '@playwright/test';

/**
 * Choose an option in a Radix (shadcn) `Select` entirely from the keyboard.
 *
 * Never click the portaled option, forced or not. Under Mobile Chrome emulation
 * Playwright mis-measures the option while the listbox is still animating in,
 * so the click can miss and leave the listbox open. An open Radix Select marks
 * everything outside it `aria-hidden`, including its own trigger. A retry that
 * looks the trigger up by role then finds nothing, every time, and the retry
 * loop has stopped retrying. The trigger is opened from the keyboard too: under
 * load, Mobile Chrome reports a neighbouring element intercepting the tap.
 *
 * Nor is the option chosen by typeahead. In the production build a space typed
 * mid-search commits whichever option has focus, so a label such as
 * "Year Only" closes the select on its space and the rest of the keystrokes
 * land on the trigger. Instead the option is focused directly and committed
 * with Enter, through the item's own key handler.
 *
 * That focus has to wait for Radix's. Radix focuses the selected option only
 * once the popper is positioned, which on a slow runner lands after the listbox
 * is visible, and would take focus back from an option focused before then.
 *
 * Each attempt starts from a closed listbox, so retrying is idempotent. The
 * Escape that closes a listbox a previous attempt left open is gated on one
 * being visible, because a bare Escape would dismiss an enclosing Dialog. The
 * attempt ends by proving the listbox closed as well as the value committed:
 * a test-id trigger ignores `aria-hidden`, so its text alone cannot show that
 * the select is no longer open.
 *
 * @param trigger - The select's trigger (the `combobox`).
 * @param optionLabel - The option's accessible name; the trigger shows it once selected.
 */
export async function selectRadixOption(
  page: Page,
  trigger: Locator,
  optionLabel: string
): Promise<void> {
  const listbox = page.getByRole('listbox');
  const option = listbox.getByRole('option', {
    name: optionLabel,
    exact: true,
  });

  await expect(async () => {
    if (await listbox.isVisible()) {
      await page.keyboard.press('Escape');
    }
    await expect(listbox).toBeHidden({ timeout: 3000 });

    await trigger.press('Enter', { timeout: 3000 });
    await expect(listbox).toBeVisible({ timeout: 3000 });
    await expect
      .poll(
        () => listbox.evaluate(node => node.contains(document.activeElement)),
        { timeout: 3000 }
      )
      .toBe(true);

    await option.focus({ timeout: 3000 });
    await expect(option).toBeFocused({ timeout: 3000 });
    await option.press('Enter', { timeout: 3000 });

    await expect(trigger).toContainText(optionLabel, { timeout: 3000 });
    await expect(listbox).toBeHidden({ timeout: 3000 });
  }).toPass({ timeout: 30000 });
}
