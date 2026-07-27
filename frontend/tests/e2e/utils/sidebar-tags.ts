/**
 * Shared helpers for driving the sidebar tag trees in E2E tests.
 *
 * Extracted from `sidebar-tag-management.spec.ts` when `journal-history.spec.ts`
 * needed to rename a tag through the same real UI to assert the resulting
 * activity-feed entry. Both specs open the sidebar and the per-tag management
 * dialog identically, so the gesture retries and the mobile-Sheet handling live
 * here once rather than being copied per spec.
 */

import { expect, type Locator, type Page } from '@playwright/test';

const ARIA_EXPANDED = 'aria-expanded';

/**
 * Ensure the sidebar is visible and the given section is expanded.
 * On mobile viewports, this opens the hamburger Sheet first.
 */
export async function ensureSidebarOpen(page: Page, section = 'Contacts') {
  const isMobile =
    page.viewportSize()?.width && page.viewportSize()!.width < 768;
  if (isMobile) {
    const mobileTrigger = page.getByTestId('mobile-nav-trigger');
    // Gate on the trigger's `aria-expanded`, which Radix flips synchronously,
    // rather than on the heading's visibility: the Sheet slides in over 500ms,
    // so a one-shot visibility check taken mid-animation reports "closed" for a
    // Sheet that is already open, and the resulting second click is swallowed by
    // the open Sheet's overlay.
    const isSheetOpen =
      (await mobileTrigger.getAttribute(ARIA_EXPANDED)) === 'true';
    if (!isSheetOpen) {
      await mobileTrigger.click();
    }
    // Auto-retrying, so it waits out the slide-in either way.
    await expect(
      page.getByRole('heading', { name: 'Navigation' })
    ).toBeVisible();
  }

  // Expand the requested section if collapsed
  const sectionHeader = page.getByRole('button', { name: section });
  await expect(sectionHeader).toBeVisible();
  const isExpanded = await sectionHeader.getAttribute(ARIA_EXPANDED);
  if (isExpanded === 'false') {
    await sectionHeader.click();
  }
  await expect(sectionHeader).toHaveAttribute(ARIA_EXPANDED, 'true');
}

/** The Journals navigation group, which hosts the journal tag tree. */
export function journalSection(page: Page): Locator {
  return page.getByRole('group', { name: 'Journals' });
}

/** The sidebar row for a journal tag, located by the tag's id. */
export function journalTagLink(page: Page, tagId: string): Locator {
  return journalSection(page).getByTestId(`nav-link-journal-tag-${tagId}`);
}

/** Opens a journal tag row's management menu and chooses Edit Tag. */
export async function openEditDialogForTag(
  page: Page,
  tagId: string
): Promise<Locator> {
  const tagLink = journalTagLink(page, tagId);
  await expect(tagLink).toBeVisible({ timeout: 15000 });

  // Retry the gesture: the click can be swallowed during hydration.
  const editMenuItem = page.getByRole('menuitem', { name: 'Edit Tag' });
  await expect(async () => {
    await tagLink.click({ button: 'right' });
    await expect(editMenuItem).toBeVisible({ timeout: 2000 });
  }).toPass();

  const dialog = page.getByRole('dialog', { name: 'Edit Tag' });
  await expect(async () => {
    await editMenuItem.click();
    await expect(dialog).toBeVisible({ timeout: 2000 });
  }).toPass();

  return dialog;
}
