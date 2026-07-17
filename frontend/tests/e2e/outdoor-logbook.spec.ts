/**
 * E2E Tests for the Outdoor Logbook overview page: the incomplete activities
 * review (flagging with reasons, linking to the journal, dismiss,
 * show-dismissed and un-dismiss flows) and the dashboard widgets (upcoming
 * activities, recent activity totals).
 */

import { test, expect } from './fixtures';
import { ContactTestHelpers } from './utils/test-helpers';

const LIST_API = '/api/journals/incomplete-outdoor-activities';

/**
 * Noon local time offset by `days` from today, so entries fall on stable
 * calendar dates well clear of the timezone-anchored dashboard window
 * boundaries.
 */
function noonOffsetDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
}

/** Today at noon local time, so entries fall on a stable calendar date. */
function todayNoon(): string {
  return noonOffsetDays(0);
}

test.describe('Outdoor Logbook — incomplete activities review', () => {
  test('flags an incomplete canyoning journal with its reasons and links to the journal', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    await dataManager.clearAllJournals();

    // A canyoning journal with no type attributes, no template, and no
    // participants matches all three incompleteness rules.
    const journal = await dataManager.createJournal({
      title: 'Incomplete Canyon Trip',
      content: 'A canyon trip missing its details',
      event_date_range: { start: todayNoon(), end: todayNoon() },
      types: ['canyoning'],
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    await contactTestHelpers.navigateToAuthenticatedPage(
      '/journals/outdoor-logbook'
    );

    await expect(
      page.getByRole('heading', { name: 'Outdoor Logbook' })
    ).toBeVisible();

    const item = page.getByTestId(`incomplete-activity-item-${journal.id}`);
    await expect(item).toBeVisible({ timeout: 15000 });

    // All three reasons are shown as distinct badges
    await expect(item.getByTestId('reason-badge-no_attributes')).toHaveText(
      /No attributes set/
    );
    await expect(item.getByTestId('reason-badge-missing_template')).toHaveText(
      /Missing template/
    );
    await expect(item.getByTestId('reason-badge-no_participants')).toHaveText(
      /No participants/
    );

    // Type icons include the canyoning badge
    await expect(item.getByTestId('type-badge-canyoning')).toBeVisible();

    // The title links to the journal detail screen
    await item.getByRole('link', { name: journal.title }).click();
    await expect(page).toHaveURL(new RegExp(`/journals/${journal.id}$`));
  });

  test('dismisses an entry, reveals it via show-dismissed, and un-dismisses it', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    await dataManager.clearAllJournals();

    const journal = await dataManager.createJournal({
      title: 'Genuinely Solo Canyon',
      content: 'A solo canyon trip that is fine as-is',
      event_date_range: { start: todayNoon(), end: todayNoon() },
      types: ['canyoning'],
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    await contactTestHelpers.navigateToAuthenticatedPage(
      '/journals/outdoor-logbook'
    );

    const item = page.getByTestId(`incomplete-activity-item-${journal.id}`);
    await expect(item).toBeVisible({ timeout: 15000 });

    // Dismiss: wait for the POST and the subsequent React Query list refetch
    const dismissBtn = page.getByTestId(`incomplete-dismiss-btn-${journal.id}`);
    await dismissBtn.scrollIntoViewIfNeeded();
    await expect(dismissBtn).toBeEnabled();
    let dismissPostFinished = false;
    await Promise.all([
      page.waitForResponse(resp => {
        if (
          resp.url().includes(`${LIST_API}/${journal.id}/dismiss`) &&
          resp.request().method() === 'POST' &&
          resp.ok()
        ) {
          dismissPostFinished = true;
          return true;
        }
        return false;
      }),
      page.waitForResponse(
        resp =>
          dismissPostFinished &&
          resp.url().includes(LIST_API) &&
          !resp.url().includes('/dismiss') &&
          resp.request().method() === 'GET' &&
          resp.ok()
      ),
      dismissBtn.click(),
    ]);

    await expect(
      page.getByText('Activity dismissed from the incomplete review')
    ).toBeVisible();
    await expect(item).not.toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('incomplete-empty-state')).toBeVisible();

    // Show dismissed: the entry reappears muted with an un-dismiss control
    const showDismissedSwitch = page.getByRole('switch', {
      name: 'Show dismissed',
    });
    await Promise.all([
      page.waitForResponse(
        resp =>
          resp.url().includes('include_dismissed=true') &&
          resp.request().method() === 'GET' &&
          resp.ok()
      ),
      showDismissedSwitch.click(),
    ]);

    await expect(item).toBeVisible({ timeout: 15000 });
    await expect(item).toHaveAttribute('data-dismissed', 'true');

    // Un-dismiss: wait for the POST and the list refetch
    const undismissBtn = page.getByTestId(
      `incomplete-undismiss-btn-${journal.id}`
    );
    await undismissBtn.scrollIntoViewIfNeeded();
    await expect(undismissBtn).toBeEnabled();
    let undismissPostFinished = false;
    await Promise.all([
      page.waitForResponse(resp => {
        if (
          resp.url().includes(`${LIST_API}/${journal.id}/undismiss`) &&
          resp.request().method() === 'POST' &&
          resp.ok()
        ) {
          undismissPostFinished = true;
          return true;
        }
        return false;
      }),
      page.waitForResponse(
        resp =>
          undismissPostFinished &&
          resp.url().includes(LIST_API) &&
          !resp.url().includes('/undismiss') &&
          resp.request().method() === 'GET' &&
          resp.ok()
      ),
      undismissBtn.click(),
    ]);

    await expect(
      page.getByText('Activity restored to the incomplete review')
    ).toBeVisible();

    // Back in the default (non-dismissed) list, the entry is live again
    await Promise.all([
      page.waitForResponse(
        resp =>
          resp.url().includes(LIST_API) &&
          !resp.url().includes('include_dismissed=true') &&
          !resp.url().includes('/dismiss') &&
          resp.request().method() === 'GET' &&
          resp.ok()
      ),
      showDismissedSwitch.click(),
    ]);

    await expect(item).toBeVisible({ timeout: 15000 });
    await expect(item).toHaveAttribute('data-dismissed', 'false');
    await expect(
      page.getByTestId(`incomplete-dismiss-btn-${journal.id}`)
    ).toBeVisible();
  });

  test('does not flag a complete bushwalking journal', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    await dataManager.clearAllJournals();

    // Bushwalking with an attribute set: rule 1 satisfied, rule 2 not
    // applicable, rule 3 exempt (solo hikes are expected).
    const journal = await dataManager.createJournal({
      title: 'Complete Solo Hike',
      content: 'A well-recorded solo bushwalk',
      event_date_range: { start: todayNoon(), end: todayNoon() },
      types: ['bushwalking'],
      type_data: {
        bushwalking: { track_grading: 'Grade 3' },
      },
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    await contactTestHelpers.navigateToAuthenticatedPage(
      '/journals/outdoor-logbook'
    );

    await expect(page.getByTestId('incomplete-list-ready')).toBeVisible({
      timeout: 15000,
    });
    await expect(
      page.getByTestId(`incomplete-activity-item-${journal.id}`)
    ).toBeHidden();
    await expect(page.getByTestId('incomplete-empty-state')).toBeVisible();
  });
});

test.describe('Outdoor Logbook — dashboard widgets', () => {
  test('shows upcoming activities and recent activity totals for seeded journals', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    await dataManager.clearAllJournals();

    // Future journals appear in the upcoming widget only; past journals count
    // in the totals windows only (−10d in both windows, −100d in 365d only).
    const futureCanyon = await dataManager.createJournal({
      title: 'Future Canyon',
      content: 'An upcoming canyoning trip',
      event_date_range: { start: noonOffsetDays(7), end: noonOffsetDays(7) },
      types: ['canyoning'],
    });
    const planning = await dataManager.createJournal({
      title: 'Winter Trip Planning',
      content: 'Planning session for the winter trip',
      event_date_range: { start: noonOffsetDays(14), end: noonOffsetDays(14) },
      types: ['outdoor_planning'],
    });
    const recentCanyon = await dataManager.createJournal({
      title: 'Recent Canyon',
      content: 'A canyoning trip from last week',
      event_date_range: {
        start: noonOffsetDays(-10),
        end: noonOffsetDays(-10),
      },
      types: ['canyoning'],
    });
    await dataManager.createJournal({
      title: 'Autumn Hike',
      content: 'A bushwalk from a few months back',
      event_date_range: {
        start: noonOffsetDays(-100),
        end: noonOffsetDays(-100),
      },
      types: ['bushwalking'],
    });

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    await contactTestHelpers.navigateToAuthenticatedPage(
      '/journals/outdoor-logbook'
    );

    // Upcoming widget: both future entries visible, soonest first; the past
    // journal stays out of the list.
    const upcoming = page.getByTestId('upcoming-ready');
    await expect(upcoming).toBeVisible({ timeout: 15000 });

    const futureItem = upcoming.getByTestId(
      `upcoming-activity-item-${futureCanyon.id}`
    );
    await expect(futureItem).toBeVisible();
    await expect(
      upcoming.getByTestId(`upcoming-activity-item-${planning.id}`)
    ).toBeVisible();
    await expect(
      upcoming.getByTestId(`upcoming-activity-item-${recentCanyon.id}`)
    ).toBeHidden();

    // Soonest first: the +7d canyon precedes the +14d planning event
    // (createJournal suffixes titles for uniqueness, so assert on the
    // returned title)
    await expect(
      upcoming.getByRole('listitem').first().getByRole('link')
    ).toHaveText(futureCanyon.title);

    // Type badges: presence, not exact sets — canyoning renders its
    // dependency-added badges too.
    await expect(futureItem.getByTestId('type-badge-canyoning')).toBeVisible();
    const planningItem = upcoming.getByTestId(
      `upcoming-activity-item-${planning.id}`
    );
    await expect(
      planningItem.getByTestId('type-badge-outdoor_planning')
    ).toBeVisible();

    // Totals widget: −10d canyon in both windows; −100d bushwalk in the
    // 365-day window only; future journals count in neither.
    const totals = page.getByTestId('totals-ready');
    await expect(totals).toBeVisible({ timeout: 15000 });
    await expect(totals.getByTestId('totals-30d-canyoning')).toHaveText('1');
    await expect(totals.getByTestId('totals-365d-canyoning')).toHaveText('1');
    await expect(totals.getByTestId('totals-30d-bushwalking')).toHaveText('0');
    await expect(totals.getByTestId('totals-365d-bushwalking')).toHaveText('1');

    // The upcoming entry links to the journal detail screen
    await futureItem.getByRole('link', { name: futureCanyon.title }).click();
    await expect(page).toHaveURL(new RegExp(`/journals/${futureCanyon.id}$`));
  });

  test('shows empty states when there is no outdoor activity', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new (await import('./data-management')).TestDataManager(
      page
    );
    const contactTestHelpers = new ContactTestHelpers(page);

    await dataManager.clearAllJournals();

    testCleanup(async () => {
      await dataManager.clearAllJournals();
    });

    await contactTestHelpers.navigateToAuthenticatedPage(
      '/journals/outdoor-logbook'
    );

    await expect(page.getByTestId('upcoming-ready')).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId('upcoming-empty-state')).toBeVisible();

    await expect(page.getByTestId('totals-ready')).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId('totals-empty-state')).toBeVisible();
  });
});
