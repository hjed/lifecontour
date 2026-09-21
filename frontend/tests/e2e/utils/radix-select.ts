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
 * Typing must wait for focus to enter the listbox. Radix only moves focus there
 * once the popper is positioned, which on a slow runner lands after the listbox
 * is already visible. Until then keys reach the trigger, whose own typeahead
 * changes the value while Enter, an open key, leaves the listbox open.
 *
 * Each attempt starts from a closed listbox, so retrying is idempotent. The
 * Escape that closes a listbox a previous attempt left open is gated on one
 * being visible, because a bare Escape would dismiss an enclosing Dialog. The
 * attempt ends by proving the listbox closed as well as the value committed:
 * a test-id trigger ignores `aria-hidden`, so its text alone cannot show that
 * the select is no longer open.
 *
 * @param trigger - The select's trigger (the `combobox`).
 * @param optionLabel - The option's visible label; the trigger shows it once selected.
 */
export async function selectRadixOption(
  page: Page,
  trigger: Locator,
  optionLabel: string
): Promise<void> {
  const listbox = page.getByRole('listbox');

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

    await page.keyboard.type(optionLabel, { delay: 50 });
    await page.keyboard.press('Enter');

    await expect(trigger).toContainText(optionLabel, { timeout: 3000 });
    await expect(listbox).toBeHidden({ timeout: 3000 });
  }).toPass({ timeout: 30000 });
}
