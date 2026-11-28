import { expect, type Locator, type Page } from '@playwright/test';

/**
 * The list page (`/tasks/[id]`), as the task-lists specs drive it.
 *
 * The open-tasks region renders only once the list and its tasks have loaded,
 * so reaching it means the page is ready to be acted on.
 */

export function openTasksRegion(page: Page): Locator {
  return page.getByRole('region', { name: 'Open tasks' });
}

export async function gotoTaskList(page: Page, listId: string): Promise<void> {
  await page.goto(`/tasks/${listId}`);
  await expect(openTasksRegion(page)).toBeVisible();
}

export function openTaskTexts(page: Page): Locator {
  return openTasksRegion(page).getByTestId('task-row-text');
}

export function taskCheckbox(page: Page, text: string): Locator {
  return openTasksRegion(page).getByRole('checkbox', {
    name: `Done: ${text}`,
  });
}

/**
 * Tick a task off and wait for it to leave the open tasks.
 *
 * The click is repeated only while the box is still unticked, so a click lost
 * to a re-render is retried and a landed one is never undone by a second.
 */
export async function completeTask(page: Page, text: string): Promise<void> {
  const checkbox = taskCheckbox(page, text);
  await expect(async () => {
    const stillOpen =
      (await checkbox.count()) > 0 &&
      (await checkbox.getAttribute('aria-checked')) === 'false';
    if (stillOpen) await checkbox.click({ timeout: 2_000 });
    await expect(checkbox).toBeHidden({ timeout: 3_000 });
  }).toPass({ timeout: 15_000 });
}
