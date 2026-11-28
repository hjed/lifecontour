/**
 * E2E tests for ITER18-003 Phase 9 — task history on the journal, and a task's
 * record on a linked contact's activity history.
 *
 * Two facts the unit and integration suites cannot state together:
 *
 * 1. **A task change made in the UI reaches the feed carrying UI provenance.**
 *    The service, the outbox, the relay, the projection and the read all have
 *    their own tests; what only a browser can say is that the change a person
 *    makes by clicking travels the whole chain and is attributed to the web
 *    interface rather than to a background process.
 * 2. **A task linked to a contact appears on their history and offers no
 *    action there.** The specification's *Where tasks appear* allows exactly
 *    two working surfaces and says a record of the past is not a third: "entries
 *    are not actionable from there".
 *
 * History is projected **asynchronously**, so every assertion about a change
 * that has just been made polls the read API with `toPass` before looking at
 * the page. Each test builds its own data; nothing here branches on what it
 * finds.
 */

import { test, expect } from './fixtures';
import { TestDataManager, utcDayOffset } from './data-management';
import { formatIsoDate } from '../../src/lib/date-utils';

const PROJECTION_TIMEOUT = 30000;

/**
 * Poll a history endpoint until an entry matching `matches` appears.
 *
 * Mirrors the helpers in `contact-activity-feed.spec.ts` and
 * `journal-history.spec.ts` — same reason, same shape.
 */
async function waitForHistoryEntry(
  request: import('@playwright/test').APIRequestContext,
  path: string,
  matches: (attrs: {
    entity_type: string;
    entity_id: number;
    field_name: string;
    source: string;
    old_value: string | null;
    new_value: string | null;
  }) => boolean
): Promise<void> {
  await expect(async () => {
    const response = await request.get(path);
    expect(response.ok()).toBeTruthy();
    const json = await response.json();
    expect(Array.isArray(json.data)).toBe(true);
    const found = json.data.some(
      (entry: { attributes: Parameters<typeof matches>[0] }) =>
        matches(entry.attributes)
    );
    expect(found).toBe(true);
  }).toPass({ timeout: PROJECTION_TIMEOUT });
}

test.describe('Task activity history', () => {
  test('a status change made in the UI appears in the task’s history with UI provenance', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const data = new TestDataManager(page);
    testCleanup(async () => data.cleanup());

    const [creating, due] = await data.createTaskAnchorJournals('History');
    const task = await data.createTask({
      creatingJournalId: creating.id,
      dueJournalId: due.id,
      text: 'Confirm the booking',
    });

    await page.goto(`/journals/${creating.id}`);
    const row = page.getByTestId(`journal-task-${task.id}`);
    await expect(row).toBeVisible({ timeout: 15000 });

    // The change under test: made by clicking, not by an API call.
    await row.getByTestId('journal-task-action-done').click();
    // The offer changes with the status, so the arrival of the "return to not
    // done" action is the row saying the write landed — and unlike the badge
    // text it cannot be confused with the button that was just clicked.
    await expect(row.getByTestId('journal-task-action-not-done')).toBeVisible();

    // Projection is asynchronous, so wait for the row to exist before asking
    // the page to render it.
    await waitForHistoryEntry(
      page.request,
      `/api/tasks/${task.id}/history`,
      attrs =>
        attrs.field_name === 'status' &&
        attrs.new_value === 'done' &&
        attrs.source === 'ui'
    );

    await page.reload();
    const rowAfterReload = page.getByTestId(`journal-task-${task.id}`);
    await expect(rowAfterReload).toBeVisible({ timeout: 15000 });

    const trigger = rowAfterReload.getByRole('button', {
      name: 'Show history for “Confirm the booking”',
    });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await trigger.click();

    const feed = rowAfterReload.getByTestId('activity-feed');
    await expect(feed).toBeVisible();
    await expect(
      feed.getByText('Status changed from Not done to Done')
    ).toBeVisible({ timeout: PROJECTION_TIMEOUT });
    await expect(
      feed.getByTestId('provenance-trigger-ui').first()
    ).toBeVisible();
  });

  test('a task’s history collapses again and starts closed', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const data = new TestDataManager(page);
    testCleanup(async () => data.cleanup());

    const [creating, due] = await data.createTaskAnchorJournals('Disclosure');
    const task = await data.createTask({
      creatingJournalId: creating.id,
      dueJournalId: due.id,
      text: 'Pack the ropes',
    });

    await page.goto(`/journals/${creating.id}`);
    const row = page.getByTestId(`journal-task-${task.id}`);
    await expect(row).toBeVisible({ timeout: 15000 });

    // Closed to begin with: a journal holding many tasks shows a list, not a
    // wall of histories.
    await expect(row.getByTestId('activity-feed')).toBeHidden();

    await row
      .getByRole('button', { name: 'Show history for “Pack the ropes”' })
      .click();
    await expect(row.getByTestId('activity-feed')).toBeVisible();

    await row
      .getByRole('button', { name: 'Hide history for “Pack the ropes”' })
      .click();
    await expect(row.getByTestId('activity-feed')).toBeHidden();
  });

  test('a flag and icon set on a journal-only task read as history lines', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const data = new TestDataManager(page);
    testCleanup(async () => data.cleanup());

    const [creating, due] = await data.createTaskAnchorJournals('Marks');
    const task = await data.createTask({
      creatingJournalId: creating.id,
      dueJournalId: due.id,
      text: 'Charge the head torch',
    });

    // No control sets these until the task details panel exists, so the
    // write goes through the endpoint that panel will use.
    await data.setTaskFlagAndIcon(task.id, { flagged: true, icon: 'tent' });

    const historyPath = `/api/tasks/${task.id}/history`;
    await waitForHistoryEntry(
      page.request,
      historyPath,
      attrs => attrs.field_name === 'flagged' && attrs.new_value === 'True'
    );
    await waitForHistoryEntry(
      page.request,
      historyPath,
      attrs => attrs.field_name === 'icon' && attrs.new_value === 'tent'
    );

    await page.goto(`/journals/${creating.id}`);
    const row = page.getByTestId(`journal-task-${task.id}`);
    await expect(row).toBeVisible({ timeout: 15000 });

    const trigger = row.getByRole('button', {
      name: 'Show history for “Charge the head torch”',
    });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await trigger.click();

    const feed = row.getByTestId('activity-feed');
    await expect(feed).toBeVisible();
    await expect(feed.getByText('Flagged', { exact: true })).toBeVisible({
      timeout: PROJECTION_TIMEOUT,
    });
    await expect(feed.getByText('Icon set', { exact: true })).toBeVisible({
      timeout: PROJECTION_TIMEOUT,
    });
  });

  test('a journal-only task added to a list and moved to another reads as history lines', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const data = new TestDataManager(page);
    testCleanup(async () => data.cleanup());

    const [creating, due] = await data.createTaskAnchorJournals('Moves');
    const task = await data.createTask({
      creatingJournalId: creating.id,
      dueJournalId: due.id,
      text: 'Wax the skis',
    });
    const first = await data.createTaskList('Moves first list');
    const second = await data.createTaskList('Moves second list');

    await data.moveTaskToList(task.id, first.id);
    await data.moveTaskToList(task.id, second.id);

    const historyPath = `/api/tasks/${task.id}/history`;
    await waitForHistoryEntry(
      page.request,
      historyPath,
      attrs =>
        attrs.field_name === 'task_list_id' && attrs.new_value === second.id
    );

    await page.goto(`/journals/${creating.id}`);
    const row = page.getByTestId(`journal-task-${task.id}`);
    await expect(row).toBeVisible({ timeout: 15000 });

    const trigger = row.getByRole('button', {
      name: 'Show history for “Wax the skis”',
    });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await trigger.click();
    // Expanded, the same button is named for hiding the history.
    await expect(
      row.getByRole('button', { name: 'Hide history for “Wax the skis”' })
    ).toHaveAttribute('aria-expanded', 'true');

    const feed = row.getByTestId('activity-feed');
    await expect(feed).toBeVisible();
    await expect(
      feed.getByText('Added to a list', { exact: true })
    ).toBeVisible({ timeout: PROJECTION_TIMEOUT });
    await expect(
      feed.getByText('Moved to another list', { exact: true })
    ).toBeVisible({ timeout: PROJECTION_TIMEOUT });
  });

  test('a task taken off its list reads as a history line', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const data = new TestDataManager(page);
    testCleanup(async () => data.cleanup());

    const [creating, due] = await data.createTaskAnchorJournals('Removal');
    const task = await data.createTask({
      creatingJournalId: creating.id,
      dueJournalId: due.id,
      text: 'Return the hire car',
    });
    const list = await data.createTaskList('Removal list');

    await data.moveTaskToList(task.id, list.id);
    await data.removeTaskFromList(task.id);

    const historyPath = `/api/tasks/${task.id}/history`;
    await waitForHistoryEntry(
      page.request,
      historyPath,
      attrs =>
        attrs.field_name === 'task_list_id' &&
        attrs.old_value === list.id &&
        attrs.new_value === null
    );

    await page.goto(`/journals/${creating.id}`);
    const row = page.getByTestId(`journal-task-${task.id}`);
    await expect(row).toBeVisible({ timeout: 15000 });

    const trigger = row.getByRole('button', {
      name: 'Show history for “Return the hire car”',
    });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await trigger.click();
    await expect(
      row.getByRole('button', {
        name: 'Hide history for “Return the hire car”',
      })
    ).toHaveAttribute('aria-expanded', 'true');

    const feed = row.getByTestId('activity-feed');
    await expect(feed).toBeVisible();
    await expect(
      feed.getByText('Added to a list', { exact: true })
    ).toBeVisible({ timeout: PROJECTION_TIMEOUT });
    await expect(
      feed.getByText('Removed from its list', { exact: true })
    ).toBeVisible({ timeout: PROJECTION_TIMEOUT });
  });

  test('a due date set on a list task reads as a history line', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const data = new TestDataManager(page);
    testCleanup(async () => data.cleanup());

    const journal = await data.createFutureJournal({
      title: 'Coast walk',
      daysAhead: 3,
    });
    const list = await data.createTaskList('Coast walk packing');
    const task = await data.createListTask({
      taskListId: list.id,
      text: 'Buy blister plasters',
    });
    // A mention puts the list task on the journal page, where its history
    // trigger lives until the list page exists.
    await data.attachTaskMention(task.id, journal.id);

    // The e2e user has no timezone, so the backend's "today" is UTC's; ten
    // days out is today or later in every zone.
    const dueDate = utcDayOffset(10).slice(0, 10);

    // No control sets this until the task details panel exists, so the write
    // goes through the endpoint that panel will use.
    const response = await page.request.patch(`/api/tasks/${task.id}`, {
      headers: { 'Content-Type': 'application/json' },
      data: {
        data: {
          type: 'tasks',
          id: String(task.id),
          attributes: { due_date: dueDate },
        },
      },
    });
    await expect(response).toBeOK();

    await waitForHistoryEntry(
      page.request,
      `/api/tasks/${task.id}/history`,
      attrs => attrs.field_name === 'due_date' && attrs.new_value === dueDate
    );

    await page.goto(`/journals/${journal.id}`);
    const row = page
      .getByTestId('journal-tasks-group-mentioned')
      .getByTestId(`journal-task-${task.id}`);
    await expect(row).toBeVisible({ timeout: 15000 });

    const trigger = row.getByRole('button', {
      name: 'Show history for “Buy blister plasters”',
    });
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await trigger.click();

    const feed = row.getByTestId('activity-feed');
    await expect(
      feed.getByText(`Due date set to ${formatIsoDate(dueDate)}`, {
        exact: true,
      })
    ).toBeVisible({ timeout: PROJECTION_TIMEOUT });
  });

  test('a task linked to a contact appears on their activity history and offers no action', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const data = new TestDataManager(page);
    testCleanup(async () => data.cleanup());

    const contact = await data.createContact({
      firstName: 'Tasked',
      lastName: 'Person',
    });
    const [creating, due] =
      await data.createTaskAnchorJournals('ContactRecord');
    const task = await data.createTask({
      creatingJournalId: creating.id,
      dueJournalId: due.id,
      text: 'Return the borrowed harness',
    });

    await data.linkTaskToContact(task.id, contact.id);

    await waitForHistoryEntry(
      page.request,
      `/api/contacts/${contact.id}/history`,
      attrs =>
        attrs.entity_type === 'task' && attrs.entity_id === Number(task.id)
    );

    await page.goto(`/contacts/${contact.id}`);
    const feed = page.getByTestId('activity-feed');
    await expect(feed).toBeVisible({ timeout: 15000 });

    // The entry names the commitment: a task has no route of its own, so the
    // name is the only thing that makes this a record *of something*.
    const entry = feed
      .locator('[data-testid^="activity-item-"]')
      .filter({ hasText: 'Linked to a task: “Return the borrowed harness”' });
    await expect(entry).toHaveCount(1, { timeout: PROJECTION_TIMEOUT });
    await expect(entry).toBeVisible();

    // Read-only, and provably so. The provenance icon is a button because it
    // carries the tooltip; nothing else in the entry is interactive.
    // Both counts are pinned to literals rather than to each other: deriving
    // the expected number from the DOM would let an entry that rendered no
    // provenance trigger and one stray action button satisfy 1 === 1.
    await expect(
      entry.locator('[data-testid^="provenance-trigger-"]')
    ).toHaveCount(1);
    await expect(entry.getByRole('button')).toHaveCount(1);
    await expect(entry.getByRole('link')).toHaveCount(0);
    await expect(entry.getByRole('checkbox')).toHaveCount(0);

    // And the feed itself cannot be narrowed to "everything still outstanding".
    await expect(feed.getByRole('combobox')).toHaveCount(0);
    await expect(feed.getByRole('tab')).toHaveCount(0);
    await expect(feed.getByRole('searchbox')).toHaveCount(0);
  });

  test('the record says the link came from the web interface', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const data = new TestDataManager(page);
    testCleanup(async () => data.cleanup());

    const contact = await data.createContact({
      firstName: 'Provenanced',
      lastName: 'Person',
    });
    const [creating, due] = await data.createTaskAnchorJournals('Provenance');
    const task = await data.createTask({
      creatingJournalId: creating.id,
      dueJournalId: due.id,
      text: 'Send the photos',
      contactIds: [contact.id],
    });

    await waitForHistoryEntry(
      page.request,
      `/api/contacts/${contact.id}/history`,
      attrs =>
        attrs.entity_type === 'task' &&
        attrs.entity_id === Number(task.id) &&
        attrs.source === 'ui'
    );

    await page.goto(`/contacts/${contact.id}`);
    const feed = page.getByTestId('activity-feed');
    await expect(feed).toBeVisible({ timeout: 15000 });
    await expect(
      feed.getByText('Linked to a task: “Send the photos”')
    ).toBeVisible({
      timeout: PROJECTION_TIMEOUT,
    });
    await expect(
      feed.getByTestId('provenance-trigger-ui').first()
    ).toBeVisible();
  });

  test('deleting the task closes its story on the contact’s history', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    // Without this the person is left with "linked to a task" forever, for a
    // task that no longer exists — an entry that reads as a commitment still
    // standing. The name survives the delete because it is resolved from
    // history, which is the whole reason it is not read from `tasks`.
    const page = authenticatedPage;
    const data = new TestDataManager(page);
    testCleanup(async () => data.cleanup());

    const contact = await data.createContact({
      firstName: 'Bereaved',
      lastName: 'Person',
    });
    const [creating, due] = await data.createTaskAnchorJournals('Deleted');
    const task = await data.createTask({
      creatingJournalId: creating.id,
      dueJournalId: due.id,
      text: 'Cancel the minibus',
      contactIds: [contact.id],
    });

    const deleted = await page.request.delete(`/api/tasks/${task.id}`);
    expect(deleted.status()).toBe(204);

    await waitForHistoryEntry(
      page.request,
      `/api/contacts/${contact.id}/history`,
      attrs =>
        attrs.entity_type === 'task' && attrs.field_name === '__deleted__'
    );

    await page.goto(`/contacts/${contact.id}`);
    const feed = page.getByTestId('activity-feed');
    await expect(feed).toBeVisible({ timeout: 15000 });

    await expect(
      feed.getByText('Task deleted: “Cancel the minibus”')
    ).toBeVisible({ timeout: PROJECTION_TIMEOUT });
    await expect(
      feed.getByText('Linked to a task: “Cancel the minibus”')
    ).toBeVisible();
  });
});
