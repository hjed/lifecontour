import type { Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { APP_TITLE_PATTERN } from './utils/test-helpers';
import { TestDataManager } from './data-management';

/**
 * Sidebar Navigation Tests
 *
 * Converted to use the advanced fixture-based testing system.
 * Each test uses deterministic fixtures that provide guaranteed authentication state.
 */
test.describe('Sidebar Navigation', () => {
  test.describe('Desktop Sidebar', () => {
    // Note: sidebar rendering, section expansion, active-link highlighting,
    // and the contacts section's static links are unit-tested in
    // Sidebar.test.tsx and Sidebar-dynamic-tags.test.tsx (pure client-side
    // rendering and state). What stays here is navigation that needs the real
    // router and real backend tag data.

    test('navigates to a tag page from a dynamic sidebar tag link', async ({
      taggedContactsData,
    }) => {
      // Fixture guarantees at least one tag exists, so this is deterministic.
      const { page } = taggedContactsData;
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');
      await expect(
        page.getByRole('navigation', { name: 'Main navigation' })
      ).toBeVisible();

      const tagLink = page.locator('a[href*="/contacts?tag="]').first();
      await expect(tagLink).toBeVisible({ timeout: 15000 });
      const href = await tagLink.getAttribute('href');
      expect(href).toMatch(/\/contacts\?tag=\w+/);

      await Promise.all([page.waitForURL(`**${href}`), tagLink.click()]);
      expect(page.url()).toContain('/contacts?tag=');
    });
  });

  // Note: opening the mobile sheet from the trigger and closing it on
  // navigation are unit-tested in Sidebar.test.tsx (MobileSidebar). The real
  // trigger is also exercised by every Mobile Chrome test that navigates, and
  // the responsive show/hide of trigger vs sidebar is asserted both ways by
  // 'switches between desktop and mobile sidebar based on viewport' below.

  test.describe('Responsive Behavior', () => {
    test('switches between desktop and mobile sidebar based on viewport', async ({
      authenticatedPage: page,
    }) => {
      // Start with desktop
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');
      await expect(page.getByTestId('sidebar')).toBeVisible();
      await expect(page.getByTestId('mobile-nav-trigger')).toBeHidden();

      // Switch to mobile
      await page.setViewportSize({ width: 375, height: 667 });
      await expect(page.getByTestId('sidebar')).toBeHidden();
      await expect(page.getByTestId('mobile-nav-trigger')).toBeVisible();

      // Switch back to desktop
      await page.setViewportSize({ width: 1024, height: 768 });
      await expect(page.getByTestId('sidebar')).toBeVisible();
      await expect(page.getByTestId('mobile-nav-trigger')).toBeHidden();
    });

    test('maintains navigation state across viewport changes', async ({
      authenticatedPage: page,
    }) => {
      // Start with desktop and expand journals. Inner steps use short
      // timeouts so a pre-hydration click (dropped, no handler attached yet)
      // retries instead of a single attempt consuming the whole toPass budget.
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');
      await expect(async () => {
        const journalsBtn = page.getByRole('button', { name: /journals/i });
        const expanded = await journalsBtn.getAttribute('aria-expanded', {
          timeout: 2000,
        });
        if (expanded !== 'true') {
          await journalsBtn.click({ timeout: 2000 });
        }
        await expect(
          page.getByRole('link', { name: 'All Journals' })
        ).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 30000 });

      // Switch to mobile - wait for UI to stabilize after viewport change
      await page.setViewportSize({ width: 375, height: 667 });
      // Wait for desktop sidebar to hide and mobile nav trigger to appear
      await expect(page.getByTestId('sidebar')).toBeHidden();
      await expect(page.getByTestId('mobile-nav-trigger')).toBeVisible();
      await expect(async () => {
        // Only click the trigger if the mobile dialog is NOT already open.
        // Clicking a toggle inside toPass() retries can close it on the
        // next attempt, causing an infinite retry loop.
        const dialogVisible = await page
          .locator('[role="dialog"]')
          .isVisible()
          .catch(() => false);
        if (!dialogVisible) {
          await page.getByTestId('mobile-nav-trigger').click({ timeout: 2000 });
        }
        // Journals should still be expanded. Short inner timeouts keep a
        // failed attempt from consuming the whole toPass budget.
        await expect(
          page.getByRole('button', { name: /journals/i })
        ).toHaveAttribute('aria-expanded', 'true', { timeout: 2000 });
        await expect(
          page.getByRole('link', { name: 'All Journals' })
        ).toBeVisible({ timeout: 2000 });
      }).toPass({ timeout: 30000 });
    });
  });

  test.describe('Accessibility', () => {
    // Note: static ARIA attributes (nav role/label, section-button aria-expanded
    // and aria-controls) are unit-tested in Sidebar.test.tsx. The keyboard test
    // below stays as e2e because real Tab focus traversal cannot be exercised in
    // jsdom.

    test('supports keyboard navigation', async ({
      authenticatedPage: page,
    }) => {
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto('/contacts');

      // Wait for sidebar to be fully loaded by ensuring key elements are present
      const navigation = page.getByRole('navigation', {
        name: 'Main navigation',
      });
      await expect(navigation).toBeVisible();

      // Ensure the contacts section is properly initialized and expanded
      const contactsButton = page.getByRole('button', { name: /contacts/i });
      await expect(contactsButton).toBeVisible();
      await expect(contactsButton).toHaveAttribute('aria-expanded', 'true');

      // Ensure the "All" link is available (indicates sidebar content is fully loaded)
      const allLink = page.getByTestId('nav-link-all');
      await expect(allLink).toBeVisible();

      // Focus on contacts button
      await contactsButton.focus();
      await expect(contactsButton).toBeFocused();

      // Tab to navigation links (should focus the "All" link)
      await page.keyboard.press('Tab');
      await expect(allLink).toBeFocused();
    });
  });

  test.describe('Hierarchical Tag Navigation', () => {
    // Note: the tag tree's expand/collapse rendering — parent toggles, hidden
    // children, leaf tags without toggles — is unit-tested in
    // Sidebar-dynamic-tags.test.tsx. The navigation test below still expands a
    // real parent on its way to the child link, so the browser-level expand
    // path stays covered.

    test('navigates to child tag page from sidebar tree', async ({
      authenticatedPage,
      isMobile,
      testCleanup,
    }) => {
      if (isMobile) test.skip();
      const page = authenticatedPage;
      const testDataManager = new TestDataManager(page);

      await page.setViewportSize({ width: 1024, height: 768 });

      // Create parent + child
      const parentName = `NavParent-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      const parentResult = await testDataManager.createTag({
        name: parentName,
      });
      const parentId = parentResult.id;

      testCleanup(async () => {
        await testDataManager.deleteTagByName(parentName).catch(() => {});
      });

      const childName = `NavChild-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
      const childResult = await testDataManager.createTag({
        name: childName,
        parent_id: parseInt(parentId),
      });
      const childId = childResult.id;

      testCleanup(async () => {
        await testDataManager.deleteTagByName(childName).catch(() => {});
      });

      // Navigate
      await page.goto('/contacts');
      await expect(page).toHaveTitle(APP_TITLE_PATTERN);

      // Reload to ensure sidebar tag tree picks up the newly created tags
      await page.reload();

      // Wait for tag tree, expand parent
      const tagTreeArea = page.getByTestId('tag-tree-container');
      await expect(tagTreeArea).toBeVisible({ timeout: 10000 });

      const expandToggle = page.getByTestId(`tag-toggle-${parentId}`);
      await expandToggle.click();

      // Click child tag link → navigate to tag page
      const childLink = page.getByTestId(`nav-link-tag-${childId}`);
      await expect(childLink).toBeVisible();
      await Promise.all([
        page.waitForURL(`**/contacts?tag=${childId}`),
        childLink.click(),
      ]);
    });
  });

  test.describe('Journal Tag Navigation', () => {
    /**
     * Generate an ISO datetime string offset from today by the given number of
     * days. Journals must use dates near "today" so they appear in the initial
     * date-window chunk loaded by the infinite scroll hook (~7 days around today).
     */
    function relativeDate(dayOffset: number): string {
      const d = new Date();
      d.setUTCDate(d.getUTCDate() + dayOffset);
      d.setUTCHours(12, 0, 0, 0); // Noon UTC to avoid boundary issues
      return d.toISOString();
    }

    /**
     * The Journals section is collapsed by default, so every journal tag
     * assertion has to open it first.
     */
    async function expandJournalsSection(page: Page): Promise<void> {
      const journalsButton = page.getByRole('button', { name: /journals/i });
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'false');
      await journalsButton.click();
      await expect(journalsButton).toHaveAttribute('aria-expanded', 'true');
    }

    test('expands a journal tag parent and navigates to the child tag filter', async ({
      authenticatedPage,
      isMobile,
      testCleanup,
    }) => {
      if (isMobile) test.skip();
      const page = authenticatedPage;
      const dataManager = new TestDataManager(page);

      await page.setViewportSize({ width: 1024, height: 768 });
      await dataManager.clearAllJournals();

      const [parentTag] = await dataManager.createJournalTags([
        { name: 'SidebarOutdoors', color: '#FF0000' },
      ]);
      const childTag = await dataManager.createJournalTag({
        name: 'SidebarClimbing',
        color: '#00FF00',
        parent_id: parentTag.id,
      });

      const journals = await dataManager.createJournals([
        {
          title: 'Sidebar Crag Day',
          content: 'Tagged with the child tag',
          event_date_range: { start: relativeDate(-1), end: relativeDate(-1) },
        },
        {
          title: 'Sidebar Untagged Errand',
          content: 'No tags at all',
          event_date_range: { start: relativeDate(0), end: relativeDate(0) },
        },
      ]);
      await dataManager.assignTagsToJournal(journals[0].id, [childTag.id]);

      testCleanup(async () => {
        await dataManager.cleanup();
      });

      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      await expandJournalsSection(page);

      // The tree renders the parent with a collapsed expand control, and the
      // child is not reachable until it is opened.
      await expect(page.getByTestId('journal-tag-tree-container')).toBeVisible({
        timeout: 10000,
      });
      await expect(
        page.getByTestId(`nav-link-journal-tag-${parentTag.id}`)
      ).toBeVisible();

      const expandToggle = page.getByTestId(
        `journal-tag-toggle-${parentTag.id}`
      );
      await expect(expandToggle).toHaveAttribute('aria-expanded', 'false');

      const childLink = page.getByTestId(`nav-link-journal-tag-${childTag.id}`);
      await expect(childLink).toBeHidden();

      await expandToggle.click();
      await expect(expandToggle).toHaveAttribute('aria-expanded', 'true');
      await expect(childLink).toBeVisible();

      // Clicking the parent includes journals carrying only its descendants
      // (the server-side expansion from ITER17-002 Phase 1).
      await Promise.all([
        page.waitForURL(`**/journals?tag=${parentTag.id}`),
        page.getByTestId(`nav-link-journal-tag-${parentTag.id}`).click(),
      ]);
      await expect(
        page.getByRole('heading', { name: /Sidebar Crag Day/i })
      ).toBeVisible({ timeout: 30000 });
      await expect(
        page.getByRole('heading', { name: /Sidebar Untagged Errand/i })
      ).toBeHidden();

      // Client-side navigation keeps the tree mounted, so the branch is still
      // open and the child is still reachable.
      await expect(childLink).toBeVisible();

      // Clicking the child filters the list to that tag.
      await Promise.all([
        page.waitForURL(`**/journals?tag=${childTag.id}`),
        childLink.click(),
      ]);

      await expect(
        page.getByRole('heading', {
          name: `${childTag.name} Journals`,
          level: 1,
        })
      ).toBeVisible();
      await expect(
        page.getByRole('heading', { name: /Sidebar Crag Day/i })
      ).toBeVisible({ timeout: 30000 });
      await expect(
        page.getByRole('heading', { name: /Sidebar Untagged Errand/i })
      ).toBeHidden();
    });

    // Note: active-tag highlighting (aria-current on the tag, not on All
    // Journals) and the absence of an expand toggle on flat journal tags are
    // unit-tested in Sidebar-journal-tags.test.tsx.
  });

  test.describe('App icon', () => {
    test('serves the SVG tab icon and every icon link resolves', async ({
      authenticatedPage: page,
    }) => {
      await page.goto('/contacts');

      const svgIcon = page.locator('link[rel="icon"][type="image/svg+xml"]');
      await expect(svgIcon).toHaveAttribute('href', /\/icon\.svg(\?|$)/);
      // The assertion above proved the href is present.
      const svgHref = (await svgIcon.getAttribute('href')) ?? '';

      const svgResponse = await page.request.get(svgHref);
      expect(svgResponse.status()).toBe(200);
      expect(svgResponse.headers()['content-type']).toContain('image/svg+xml');

      // A dangling icon link (the old '/favicon.ico' metadata) 404s.
      const hrefs = await page
        .locator('link[rel="icon"]')
        .evaluateAll(links =>
          links.map(link => link.getAttribute('href') ?? '')
        );
      for (const href of hrefs) {
        const response = await page.request.get(href);
        expect(response.status(), href).toBe(200);
      }
    });
  });
});
