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
import { TestDataManager } from './data-management';

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
