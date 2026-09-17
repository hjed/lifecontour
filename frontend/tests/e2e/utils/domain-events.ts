import { expect, type Page } from '@playwright/test';

import type {
  ConsumerGroupLag,
  OutboxBacklog,
} from '../../../src/lib/api/integrations';

/** The consumer group that marks daily summaries stale. */
export const SUMMARY_INVALIDATION_GROUP = 'summary-invalidation';

/** What still stands between a committed write and one consumer group. */
interface EventBacklog {
  unrelayed: number;
  lag: number | undefined;
  pending: number;
}

/**
 * The event backlog in front of `group`, read in the order that makes it mean
 * something.
 *
 * The outbox is read first. The relay adds an event to the stream before it
 * marks the row relayed, so once no row is unrelayed, every write committed
 * before this read is already in the stream. The group, read after that, has
 * then read (`lag`) and acknowledged (`pending`) every one of them — and a
 * consumer acknowledges an event only once its handler has committed.
 */
async function eventBacklog(page: Page, group: string): Promise<EventBacklog> {
  const outbox = await page.request.get('/api/health/outbox-backlog');
  expect(outbox.ok()).toBe(true);
  const { unrelayed_count } = (await outbox.json()) as OutboxBacklog;

  const groups = await page.request.get('/api/health/consumer-lag');
  expect(groups.ok()).toBe(true);
  const info = ((await groups.json()) as ConsumerGroupLag[]).find(
    candidate => candidate.name === group
  );
  if (!info) {
    throw new Error(`No consumer group named ${group} on the event stream`);
  }
  return { unrelayed: unrelayed_count, lag: info.lag, pending: info.pending };
}

/**
 * Wait until every domain event written so far has been applied by `group`.
 *
 * The sync point for a test that needs *all* of its writes' side effects to
 * have landed, not merely the first: the outbox relay publishes on a poll, so
 * several writes reach a consumer as one burst, and a state that the first of
 * them already produces cannot tell the burst apart from its end.
 *
 * The e2e suite runs on one worker, so the backlog is this test's own.
 */
export async function waitForDomainEventsSettled(page: Page, group: string) {
  await expect
    .poll(() => eventBacklog(page, group), {
      timeout: 30000,
      intervals: [250, 500, 1000],
    })
    .toEqual({ unrelayed: 0, lag: 0, pending: 0 });
}
