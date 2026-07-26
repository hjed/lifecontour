import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';
import { TestDataManager } from './data-management';

/**
 * Ensure the sidebar is visible and the given section is expanded.
 * On mobile viewports, this opens the hamburger Sheet first.
 */
async function ensureSidebarOpen(page: Page, section = 'Contacts') {
  const isMobile =
    page.viewportSize()?.width && page.viewportSize()!.width < 768;
  if (isMobile) {
    const mobileTrigger = page.getByTestId('mobile-nav-trigger');
    const isSidebarVisible = await page
      .getByRole('heading', { name: 'Navigation' })
      .isVisible();
    if (!isSidebarVisible) {
      await mobileTrigger.click();
      await expect(
        page.getByRole('heading', { name: 'Navigation' })
      ).toBeVisible();
    }
  }

  // Expand the requested section if collapsed
  const sectionHeader = page.getByRole('button', { name: section });
  await expect(sectionHeader).toBeVisible();
  const isExpanded = await sectionHeader.getAttribute('aria-expanded');
  if (isExpanded === 'false') {
    await sectionHeader.click();
  }
  await expect(sectionHeader).toHaveAttribute('aria-expanded', 'true');
}

test.describe('Sidebar Tag Management', () => {
  test('can create a new tag from the sidebar', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const testDataManager = new TestDataManager(page);
    const uniqueTagName = `New-Sidebar-Tag-${Date.now()}`;

    testCleanup(
      async () => await testDataManager.deleteTagByName(uniqueTagName)
    );

    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    // Click Create Tag button and wait for dialog (retrying if click is swallowed by React hydration/animations)
    const dialog = page.getByRole('dialog', { name: 'Create Tag' });
    await expect(async () => {
      await page.getByRole('button', { name: 'Create Tag' }).click();
      await expect(dialog).toBeVisible({ timeout: 2000 });
    }).toPass();

    await dialog.getByLabel('Name').fill(uniqueTagName);
    await dialog.getByPlaceholder('#000000').fill('#123456');
    await dialog.getByLabel('Description').fill('Created from sidebar');

    // Submit
    await dialog.getByRole('button', { name: 'Create Tag' }).click();

    // Verify dialog closes
    await expect(dialog).toBeHidden();

    // Verify Toast appears
    await expect(page.getByText('Tag created successfully')).toBeVisible();

    // On mobile the Sheet may have closed after the dialog interaction,
    // so re-open the sidebar before checking for the new tag link.
    await ensureSidebarOpen(page);

    // Verify tag appears in sidebar (may require React Query refetch + re-render)
    const tagLink = page.getByRole('link', {
      name: uniqueTagName,
      exact: true,
    });
    await expect(tagLink).toBeVisible({ timeout: 15000 });
  });

  test('can open context menu and edit a tag', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    const tagName = `Tag-To-Edit-${Date.now()}`;
    const newTagName = `Edited-Tag-Name-${Date.now()}`;

    await dataManager.createTags([{ name: tagName }]);
    testCleanup(async () => await dataManager.cleanup());

    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    // Wait for the tag to be visible
    const tagLink = page.getByRole('link', { name: tagName, exact: true });
    await expect(tagLink).toBeVisible();

    // Wait for context menu item
    const editMenuItem = page.getByRole('menuitem', { name: 'Edit Tag' });
    await expect(async () => {
      await tagLink.click({ button: 'right' });
      await expect(editMenuItem).toBeVisible({ timeout: 2000 });
    }).toPass();

    // Click edit and wait for dialog
    const dialog = page.getByRole('dialog', { name: 'Edit Tag' });
    await expect(async () => {
      await editMenuItem.click();
      await expect(dialog).toBeVisible({ timeout: 2000 });
    }).toPass();

    // Update name
    await dialog.getByLabel('Name').fill(newTagName);

    // Submit
    await dialog.getByRole('button', { name: 'Save Changes' }).click();

    // Verify toast
    await expect(page.getByText('Tag updated successfully')).toBeVisible();

    // Re-open sidebar on mobile to verify updated tag
    await ensureSidebarOpen(page);

    // Verify updated tag appears in sidebar
    await expect(
      page.getByRole('link', { name: newTagName, exact: true })
    ).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByRole('link', { name: tagName, exact: true })
    ).not.toBeVisible({ timeout: 10000 });
  });

  test('can delete a tag from the edit dialog', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    const tagName = `Tag-To-Delete-${Date.now()}`;

    await dataManager.createTags([{ name: tagName }]);
    testCleanup(async () => await dataManager.cleanup());

    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    const tagLink = page.getByRole('link', { name: tagName, exact: true });
    await expect(tagLink).toBeVisible();

    // Right click and edit
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

    // Click delete
    await dialog.getByRole('button', { name: 'Delete Tag' }).click();

    // Alert dialog should appear
    const alertDialog = page.getByRole('alertdialog');
    await expect(alertDialog).toBeVisible();
    await expect(alertDialog).toContainText('Are you absolutely sure?');

    // Confirm delete
    await alertDialog.getByRole('button', { name: 'Delete' }).click();

    // Verify toast
    await expect(page.getByText('Tag deleted successfully')).toBeVisible();

    // Re-open sidebar on mobile to verify tag removed
    await ensureSidebarOpen(page);

    // Verify tag disappears from sidebar
    await expect(
      page.getByRole('link', { name: tagName, exact: true })
    ).not.toBeVisible({ timeout: 10000 });
  });

  test('create dialog validates required fields', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    const dialog = page.getByRole('dialog', { name: 'Create Tag' });
    await expect(async () => {
      await page.getByRole('button', { name: 'Create Tag' }).click();
      await expect(dialog).toBeVisible({ timeout: 2000 });
    }).toPass();

    // Submit empty form
    await dialog.getByRole('button', { name: 'Create Tag' }).click();

    // Should see validation error
    await expect(dialog.getByText('Name is required')).toBeVisible();

    // Dialog should stay open
    await expect(dialog).toBeVisible();
  });

  test('edit dialog validates required fields', async ({
    authenticatedPage: page,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(page);
    const tagName = `Tag-For-Validation-${Date.now()}`;

    await dataManager.createTags([{ name: tagName }]);
    testCleanup(async () => await dataManager.cleanup());

    await page.goto('/contacts');
    await ensureSidebarOpen(page);

    const tagLink = page.getByRole('link', { name: tagName, exact: true });
    await expect(tagLink).toBeVisible();

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

    // Clear name
    await dialog.getByLabel('Name').fill('');

    // Submit
    await dialog.getByRole('button', { name: 'Save Changes' }).click();

    // Should see validation error
    await expect(dialog.getByText('Name is required')).toBeVisible();
  });

  /**
   * Journal tags are a separate namespace with their own sidebar section,
   * endpoints and dialogs, but the management experience must match the contact
   * tests above — including on the mobile Sheet.
   */
  test.describe('Journal Tags', () => {
    /**
     * Journals must sit near "today" to fall inside the initial date window the
     * infinite-scroll list loads.
     */
    function relativeDate(dayOffset: number): string {
      const d = new Date();
      d.setUTCDate(d.getUTCDate() + dayOffset);
      d.setUTCHours(12, 0, 0, 0); // Noon UTC to avoid boundary issues
      return d.toISOString();
    }

    /**
     * The Journals section's content, scoped by its accessible group name.
     *
     * On mobile both the CSS-hidden desktop sidebar and the Sheet are in the
     * DOM, so an unscoped test id matches twice. A role-based locator only
     * matches what is in the accessibility tree, which is the visible copy.
     */
    function journalSection(page: Page) {
      return page.getByRole('group', { name: 'Journals' });
    }

    /**
     * Waits for the journals list to be refetched *because of* a tag mutation.
     *
     * This is the journal-query half of the invalidation the phase promises.
     * Asserting instead that the tag chip vanishes from the list behind the
     * dialog would be an assertion on transient React Query-backed UI: a list
     * fetch already in flight when the mutation lands can settle afterwards
     * carrying pre-mutation data and, being fresh for the next five minutes, is
     * never refetched again — so the chip lingers and the test flakes.
     *
     * The predicate is a small state machine over the response stream: it
     * latches on the mutation's own response, then matches the first
     * journals-list GET after it. Registering both halves in one waiter closes
     * the gap a second `waitForResponse` would leave.
     */
    function journalsRefetchedAfter(
      page: Page,
      mutation: { pathname: string; method: string }
    ) {
      let mutated = false;
      return page.waitForResponse(response => {
        const { pathname } = new URL(response.url());
        if (
          pathname === mutation.pathname &&
          response.request().method() === mutation.method
        ) {
          mutated = response.ok();
          return false;
        }
        // A failed list GET is not a refresh — accepting one would let the
        // test pass on a refetch that never reached the cache.
        return (
          mutated &&
          pathname === '/api/journals' &&
          response.request().method() === 'GET' &&
          response.ok()
        );
      });
    }

    /** Opens a journal tag row's management menu and chooses Edit Tag. */
    async function openEditDialogForTag(page: Page, tagId: string) {
      const tagLink = journalSection(page).getByTestId(
        `nav-link-journal-tag-${tagId}`
      );
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

    test('can create a journal tag from the sidebar and assign it to a journal', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);

      const journal = await dataManager.createJournal({
        title: 'Sidebar Tag Create Target',
        content: 'Receives the tag created from the sidebar.',
        event_date_range: { start: relativeDate(-1), end: relativeDate(-1) },
      });
      testCleanup(async () => await dataManager.cleanup());

      const newTagName = `SidebarCreated-${crypto.randomUUID().slice(0, 8)}`;

      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();
      await ensureSidebarOpen(page, 'Journals');

      const dialog = page.getByRole('dialog', { name: 'Create Tag' });
      await expect(async () => {
        await journalSection(page)
          .getByTestId('journal-create-tag-button')
          .click();
        await expect(dialog).toBeVisible({ timeout: 2000 });
      }).toPass();

      await dialog.getByLabel('Name', { exact: true }).fill(newTagName);
      await dialog.getByPlaceholder('#000000').fill('#38A169');
      await dialog
        .getByLabel('Description', { exact: true })
        .fill('Created from the sidebar');

      const [createResponse] = await Promise.all([
        page.waitForResponse(
          response =>
            response.url().includes('/api/journals/tags') &&
            response.request().method() === 'POST'
        ),
        dialog.getByRole('button', { name: 'Create Tag' }).click(),
      ]);
      const createdTagId = (await createResponse.json()).data.id as string;
      dataManager.trackJournalTag(createdTagId);

      await expect(dialog).toBeHidden();
      await expect(page.getByText('Tag created successfully')).toBeVisible();

      // The mobile Sheet can close over the dialog interaction.
      await ensureSidebarOpen(page, 'Journals');

      const newTagLink = journalSection(page).getByTestId(
        `nav-link-journal-tag-${createdTagId}`
      );
      await expect(newTagLink).toBeVisible({ timeout: 15000 });
      await expect(newTagLink).toContainText(newTagName);

      // The tag is immediately usable on a journal.
      await page.goto(`/journals/${journal.id}`);
      const tagsEditor = page.getByTestId('journal-tags-editor');
      await expect(tagsEditor).toBeVisible();

      await tagsEditor.getByTestId('add-tag-button').click();
      await page.getByTestId('tag-search-input').fill(newTagName);
      await page.getByTestId(`tag-option-${createdTagId}`).click();

      const badge = tagsEditor.getByTestId(`tag-badge-${createdTagId}`);
      await expect(badge).toBeVisible({ timeout: 10000 });
      await expect(badge).toContainText(newTagName);
    });

    test('renaming a journal tag from the sidebar updates a tagged journal', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);

      const [tag] = await dataManager.createJournalTags([
        { name: 'SidebarRenameMe', color: '#FF0000' },
      ]);
      const journal = await dataManager.createJournal({
        title: 'Sidebar Rename Subject',
        content: 'Carries the renamed tag.',
        event_date_range: { start: relativeDate(-1), end: relativeDate(-1) },
      });
      await dataManager.assignTagsToJournal(journal.id, [tag.id]);
      testCleanup(async () => await dataManager.cleanup());

      const renamedTo = `SidebarRenamed-${crypto.randomUUID().slice(0, 8)}`;

      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();
      await ensureSidebarOpen(page, 'Journals');

      const dialog = await openEditDialogForTag(page, tag.id);

      await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue(
        tag.name
      );
      await dialog.getByLabel('Name', { exact: true }).fill(renamedTo);
      await Promise.all([
        page.waitForResponse(
          response =>
            response.url().includes(`/api/journals/tags/${tag.id}`) &&
            response.request().method() === 'PATCH'
        ),
        dialog.getByRole('button', { name: 'Save Changes' }).click(),
      ]);

      await expect(dialog).toBeHidden();
      await expect(page.getByText('Tag updated successfully')).toBeVisible();

      await ensureSidebarOpen(page, 'Journals');
      await expect(
        journalSection(page).getByTestId(`nav-link-journal-tag-${tag.id}`)
      ).toContainText(renamedTo, { timeout: 15000 });

      // The rename reaches the journal that carries the tag.
      await page.goto(`/journals/${journal.id}`);
      const badge = page
        .getByTestId('journal-tags-editor')
        .getByTestId(`tag-badge-${tag.id}`);
      await expect(badge).toBeVisible({ timeout: 10000 });
      await expect(badge).toContainText(renamedTo);
    });

    test('can re-parent a journal tag from the edit dialog', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);

      const [futureParent, tagToMove] = await dataManager.createJournalTags([
        { name: 'SidebarNewParent', color: '#FF0000' },
        { name: 'SidebarMoveMe', color: '#00FF00' },
      ]);
      testCleanup(async () => await dataManager.cleanup());

      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();
      await ensureSidebarOpen(page, 'Journals');

      const movedLink = journalSection(page).getByTestId(
        `nav-link-journal-tag-${tagToMove.id}`
      );
      await expect(movedLink).toBeVisible({ timeout: 15000 });
      // Both start as roots, so neither has an expand control yet.
      await expect(
        journalSection(page).getByTestId(
          `journal-tag-toggle-${futureParent.id}`
        )
      ).toHaveCount(0);

      const dialog = await openEditDialogForTag(page, tagToMove.id);

      await dialog.getByLabel('Parent Tag').click();
      await page.getByRole('option', { name: futureParent.name }).click();
      await Promise.all([
        page.waitForResponse(
          response =>
            response.url().includes(`/api/journals/tags/${tagToMove.id}`) &&
            response.request().method() === 'PATCH'
        ),
        dialog.getByRole('button', { name: 'Save Changes' }).click(),
      ]);
      await expect(dialog).toBeHidden();

      await ensureSidebarOpen(page, 'Journals');

      // The moved tag is now nested, so it hides behind its new parent's
      // collapsed expand control until that branch is opened.
      const parentToggle = journalSection(page).getByTestId(
        `journal-tag-toggle-${futureParent.id}`
      );
      await expect(parentToggle).toBeVisible({ timeout: 15000 });
      await expect(movedLink).toBeHidden();

      await parentToggle.click();
      await expect(movedLink).toBeVisible();
    });

    test('can delete a journal tag and it disappears from a journal that had it', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);

      const [tag] = await dataManager.createJournalTags([
        { name: 'SidebarDeleteMe', color: '#FF0000' },
      ]);
      const journal = await dataManager.createJournal({
        title: 'Sidebar Delete Subject',
        content: 'Loses its tag when the tag is deleted.',
        event_date_range: { start: relativeDate(-1), end: relativeDate(-1) },
      });
      await dataManager.assignTagsToJournal(journal.id, [tag.id]);
      // The tag is deleted by the test itself; cleanup tolerates the 404.
      testCleanup(async () => await dataManager.cleanup());

      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      // The tagged journal is on the list before anything is deleted, which is
      // what gives the refetch assertion below something to be about. Checked
      // before the sidebar is opened so the mobile Sheet cannot cover it.
      await expect(
        page.getByTestId(`journal-${journal.id}`).getByTestId(`tag-${tag.name}`)
      ).toBeVisible();

      await ensureSidebarOpen(page, 'Journals');

      const dialog = await openEditDialogForTag(page, tag.id);

      await dialog.getByRole('button', { name: 'Delete Tag' }).click();

      const confirmation = page.getByRole('alertdialog');
      await expect(confirmation).toBeVisible();
      await expect(confirmation).toContainText('Are you absolutely sure?');
      await expect(confirmation).toContainText(
        'remove it from all journals it is assigned to'
      );

      // The delete un-assigns the tag from every journal, so the journals list
      // must be refetched and not only the tag namespace.
      const journalsRefetched = journalsRefetchedAfter(page, {
        pathname: `/api/journals/tags/${tag.id}`,
        method: 'DELETE',
      });
      await confirmation.getByRole('button', { name: 'Delete' }).click();
      await journalsRefetched;

      await expect(dialog).toBeHidden();
      await expect(page.getByText('Tag deleted successfully')).toBeVisible();

      // The mobile Sheet can close over the dialog interaction.
      await ensureSidebarOpen(page, 'Journals');
      await expect(
        journalSection(page).getByTestId(`nav-link-journal-tag-${tag.id}`)
      ).toHaveCount(0, { timeout: 15000 });

      // Deleting un-assigns rather than being refused, so the journal survives
      // without the tag.
      await page.goto(`/journals/${journal.id}`);
      const tagsEditor = page.getByTestId('journal-tags-editor');
      await expect(tagsEditor).toBeVisible();
      await expect(tagsEditor.getByTestId(`tag-badge-${tag.id}`)).toHaveCount(
        0,
        { timeout: 10000 }
      );
    });

    test('can merge a journal tag into another and the assignment moves', async ({
      authenticatedPage: page,
      testCleanup,
    }) => {
      const dataManager = new TestDataManager(page);

      const [source, target] = await dataManager.createJournalTags([
        { name: 'SidebarMergeSource', color: '#FF0000' },
        { name: 'SidebarMergeTarget', color: '#00FF00' },
      ]);
      const journal = await dataManager.createJournal({
        title: 'Sidebar Merge Subject',
        content: 'Its tag assignment is repointed by the merge.',
        event_date_range: { start: relativeDate(-1), end: relativeDate(-1) },
      });
      await dataManager.assignTagsToJournal(journal.id, [source.id]);
      // The source tag is consumed by the merge; cleanup tolerates the 404.
      testCleanup(async () => await dataManager.cleanup());

      await page.goto('/journals');
      await expect(page.getByTestId('journals-list-ready')).toBeVisible();

      // The source-tagged journal is on the list before the merge, which is what
      // gives the refetch assertion below something to be about. Checked before
      // the sidebar is opened so the mobile Sheet cannot cover the row.
      await expect(
        page
          .getByTestId(`journal-${journal.id}`)
          .getByTestId(`tag-${source.name}`)
      ).toBeVisible();

      await ensureSidebarOpen(page, 'Journals');

      const dialog = await openEditDialogForTag(page, source.id);

      await dialog.getByLabel('Merge into').click();
      await page.getByRole('option', { name: target.name }).click();
      await dialog.getByRole('button', { name: 'Merge', exact: true }).click();

      const confirmation = page.getByRole('alertdialog');
      await expect(confirmation).toBeVisible();
      await expect(confirmation).toContainText(source.name);

      // The merge repoints every assignment, so the journals list must be
      // refetched and not only the tag namespace.
      const journalsRefetched = journalsRefetchedAfter(page, {
        pathname: `/api/journals/tags/${source.id}/merge`,
        method: 'POST',
      });
      await confirmation.getByRole('button', { name: 'Confirm Merge' }).click();
      await journalsRefetched;

      await expect(dialog).toBeHidden();
      await expect(page.getByText('Tag successfully merged')).toBeVisible();

      await ensureSidebarOpen(page, 'Journals');
      await expect(
        journalSection(page).getByTestId(`nav-link-journal-tag-${source.id}`)
      ).toHaveCount(0, { timeout: 15000 });
      await expect(
        journalSection(page).getByTestId(`nav-link-journal-tag-${target.id}`)
      ).toBeVisible();

      // The journal tagged with the source now carries the target instead.
      await page.goto(`/journals/${journal.id}`);
      const tagsEditor = page.getByTestId('journal-tags-editor');
      await expect(tagsEditor).toBeVisible();
      await expect(
        tagsEditor.getByTestId(`tag-badge-${target.id}`)
      ).toBeVisible({ timeout: 10000 });
      await expect(
        tagsEditor.getByTestId(`tag-badge-${source.id}`)
      ).toHaveCount(0);
    });
  });
});
