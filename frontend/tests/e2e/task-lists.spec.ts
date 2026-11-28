import type { Page } from '@playwright/test';

import { TestDataManager } from './data-management';
import { test, expect } from './fixtures';
import {
  expectNoHorizontalScroll,
  expectTouchHitArea,
  expectTouchTarget,
} from './utils/phone-layout';
import {
  completeTask,
  gotoTaskList,
  openTaskTexts,
  openTasksRegion,
  taskCheckbox,
} from './utils/task-lists';

/**
 * Task lists in the web app: the list page, `/tasks/[id]`.
 *
 * Every test makes its own list and tasks through the API, with a unique
 * name, so nothing here can be satisfied by another test's data. No control
 * reaches a list page yet, so each test opens it by URL.
 */

function unique(what: string): string {
  return `${what} ${crypto.randomUUID().slice(0, 8)}`;
}

function listBreadcrumb(page: Page) {
  return page.getByRole('navigation', { name: 'Breadcrumb' });
}

test.describe('Task list page', () => {
  test('names the list in its header and breadcrumb', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const data = new TestDataManager(page);
    testCleanup(async () => await data.cleanup());
    const list = await data.createTaskList(unique('House'), { icon: 'house' });
    await data.createListTask({ taskListId: list.id, text: unique('Gutters') });

    await gotoTaskList(page, list.id);

    await expect(
      page.getByRole('heading', { level: 1, name: list.name })
    ).toBeVisible();
    await expect(page.getByTestId('task-list-icon')).toBeVisible();
    await expect(page.getByTestId('task-list-summary')).toHaveText('1 open');
    const breadcrumb = listBreadcrumb(page);
    await expect(breadcrumb.getByRole('listitem')).toHaveText([
      'Home',
      'Tasks',
      list.name,
    ]);
    await expect(breadcrumb.getByRole('link')).toHaveCount(1);
    await expect(breadcrumb.getByText(list.name)).toHaveAttribute(
      'aria-current',
      'page'
    );
    await expect(
      page.getByRole('navigation', { name: 'Breadcrumb navigation' })
    ).toHaveCount(0);
  });

  test('shows the open tasks in the order the user gave them', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const data = new TestDataManager(page);
    testCleanup(async () => await data.cleanup());
    const list = await data.createTaskList(unique('Trip'));
    const trip = await data.createFutureJournal({
      title: 'Hobart trip',
      daysAhead: 5,
    });
    const tent = await data.createListTask({
      taskListId: list.id,
      text: unique('Pack the tent'),
    });
    const fuel = await data.createListTask({
      taskListId: list.id,
      text: unique('Buy fuel'),
      dueJournalId: trip.id,
    });
    const torch = await data.createListTask({
      taskListId: list.id,
      text: unique('Charge the torch'),
    });
    await data.reorderListTask(torch.id, null);

    await gotoTaskList(page, list.id);

    await expect(openTaskTexts(page)).toHaveText([
      torch.text,
      tent.text,
      fuel.text,
    ]);
    const fuelDue = openTasksRegion(page)
      .getByTestId(`task-row-${fuel.id}`)
      .getByTestId('task-row-due-journal');
    await expect(fuelDue).toContainText(trip.title);
    await expect(fuelDue).toHaveAttribute('href', `/journals/${trip.id}`);
  });

  test('completes a task in place', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const data = new TestDataManager(page);
    testCleanup(async () => await data.cleanup());
    const list = await data.createTaskList(unique('Garden'));
    const [mow, weed, water] = await Promise.all(
      ['Mow', 'Weed', 'Water'].map(text =>
        data.createListTask({ taskListId: list.id, text: unique(text) })
      )
    );
    await data.reorderListTask(weed.id, mow.id);
    await data.reorderListTask(water.id, weed.id);
    await gotoTaskList(page, list.id);
    await expect(page.getByTestId('task-list-summary')).toHaveText('3 open');

    await completeTask(page, weed.text);

    await expect(openTaskTexts(page)).toHaveText([mow.text, water.text]);
    await expect(page.getByTestId('task-list-summary')).toHaveText('2 open');
    await page.reload();
    await expect(openTaskTexts(page)).toHaveText([mow.text, water.text]);
  });

  test('completes a task from the keyboard and keeps the place', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const data = new TestDataManager(page);
    testCleanup(async () => await data.cleanup());
    const list = await data.createTaskList(unique('Desk'));
    const first = await data.createListTask({
      taskListId: list.id,
      text: unique('File receipts'),
    });
    const second = await data.createListTask({
      taskListId: list.id,
      text: unique('Pay the rates'),
    });
    const third = await data.createListTask({
      taskListId: list.id,
      text: unique('Renew the rego'),
    });
    await gotoTaskList(page, list.id);

    await taskCheckbox(page, first.text).focus();
    await page.keyboard.press('Tab');
    await expect(taskCheckbox(page, second.text)).toBeFocused();
    await page.keyboard.press('Space');

    await expect(taskCheckbox(page, second.text)).toBeHidden();
    await expect(taskCheckbox(page, third.text)).toBeFocused();
  });

  test('takes no focus back after the user clicks away from a ticked task', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const data = new TestDataManager(page);
    testCleanup(async () => await data.cleanup());
    const list = await data.createTaskList(unique('Car'));
    const tyres = await data.createListTask({
      taskListId: list.id,
      text: unique('Check the tyres'),
    });
    const oil = await data.createListTask({
      taskListId: list.id,
      text: unique('Top up the oil'),
    });
    await gotoTaskList(page, list.id);
    let releaseRefetch: () => void = () => undefined;
    const refetchHeld = new Promise<void>(resolve => {
      releaseRefetch = resolve;
    });
    await page.route(`**/api/task-lists/${list.id}/tasks`, async route => {
      await refetchHeld;
      await route.continue();
    });

    await taskCheckbox(page, tyres.text).focus();
    await page.keyboard.press('Space');
    await expect(taskCheckbox(page, tyres.text)).toHaveAttribute(
      'aria-checked',
      'true'
    );
    await page.getByRole('heading', { level: 1, name: list.name }).click();
    releaseRefetch();

    await expect(taskCheckbox(page, tyres.text)).toBeHidden();
    await expect(taskCheckbox(page, oil.text)).not.toBeFocused();
    await expect
      .poll(() => page.evaluate(() => document.activeElement === document.body))
      .toBe(true);
    await page.unrouteAll({ behavior: 'ignoreErrors' });
  });

  test('says so when the list has no open tasks', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const data = new TestDataManager(page);
    testCleanup(async () => await data.cleanup());
    const list = await data.createTaskList(unique('Empty'));

    await gotoTaskList(page, list.id);

    const region = openTasksRegion(page);
    await expect(region.getByText('No open tasks on this list')).toBeVisible();
    await expect(
      region.getByText('Tasks you add to this list will appear here.')
    ).toBeVisible();
    await expect(region.getByRole('list')).toHaveCount(0);
    await expect(page.getByTestId('task-list-summary')).toHaveText('0 open');
  });

  test('says a deleted list is not found, without waiting on retries', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const data = new TestDataManager(page);
    testCleanup(async () => await data.cleanup());
    const list = await data.createTaskList(unique('Gone'));
    await data.deleteTaskList(list.id);

    await page.goto(`/tasks/${list.id}`);

    // Retrying the refusal would hold the skeleton for about seven seconds.
    await expect(
      page.getByRole('heading', { level: 1, name: 'List not found' })
    ).toBeVisible({ timeout: 5_000 });
    await expect(page.getByRole('link', { name: 'Go home' })).toBeVisible();
  });

  test('says an id that cannot name a list is not found', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/tasks/not-a-list');

    await expect(
      page.getByRole('heading', { level: 1, name: 'List not found' })
    ).toBeVisible();
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test('fits the not-found state without sideways scroll', async ({
      authenticatedPage: page,
    }) => {
      await page.goto('/tasks/not-a-list');
      await expect(
        page.getByRole('heading', { level: 1, name: 'List not found' })
      ).toBeVisible();

      await expectNoHorizontalScroll(page);
      await expectTouchTarget(page.getByRole('link', { name: 'Go home' }));
    });

    test('fits without sideways scroll and keeps 44px targets', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const data = new TestDataManager(page);
      testCleanup(async () => await data.cleanup());
      const longWord = 'Supercalifragilisticexpialidocious'.repeat(3);
      const list = await data.createTaskList(unique(longWord), {
        icon: 'house',
      });
      const journal = await data.createFutureJournal({
        title: `${longWord}${crypto.randomUUID().slice(0, 8)}`,
        exactTitle: true,
        daysAhead: 4,
      });
      const task = await data.createListTask({
        taskListId: list.id,
        text: `${longWord}${crypto.randomUUID().slice(0, 8)}`,
        dueJournalId: journal.id,
      });

      await gotoTaskList(page, list.id);
      await expect(
        page.getByRole('heading', { level: 1, name: list.name })
      ).toBeVisible();

      await expectNoHorizontalScroll(page);
      await expectTouchTarget(
        listBreadcrumb(page).getByRole('link', { name: 'Home' })
      );
      await expectTouchHitArea(taskCheckbox(page, task.text));
      await expectTouchTarget(
        openTasksRegion(page).getByTestId('task-row-due-journal')
      );
    });
  });
});
