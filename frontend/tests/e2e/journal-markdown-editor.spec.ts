/**
 * E2E Tests for the Journal Markdown Editor
 *
 * Covers the WYSIWYG markdown editor (Tiptap) on the journal detail page and
 * the create form: rendered markdown in the view, live formatting as you type,
 * the formatting toolbar, round-trip persistence, and XSS safety.
 */

import { test, expect } from './fixtures';
import { type Locator, type Page } from '@playwright/test';
import { TestDataManager } from './data-management';

const EVENT_RANGE = {
  start: '2026-01-18T10:00:00Z',
  end: '2026-01-18T10:30:00Z',
};

// Type one character at a time with a delay so ProseMirror's async transaction
// handling does not drop keystrokes (Firefox is especially sensitive). Typing
// the closing markdown delimiters is also what triggers the live input rules.
const TYPE_DELAY = 60;

/** Create a NOTE journal with the given markdown content and open its detail page. */
async function openJournalWithContent(
  page: Page,
  testCleanup: (fn: () => Promise<void>) => void,
  content: string
): Promise<Locator> {
  const dataManager = new TestDataManager(page);
  testCleanup(async () => await dataManager.cleanup());

  const journal = await dataManager.createJournal({
    title: 'Markdown E2E',
    content,
    event_date_range: EVENT_RANGE,
    types: ['note'],
  });

  await page.goto(`/journals/${journal.id}`);
  const view = page.getByTestId('journal-content');
  await expect(view).toBeVisible();
  return view;
}

/** Enter inline edit mode and return the (empty-selection) editor surface. */
async function openInlineEditor(page: Page, view: Locator): Promise<Locator> {
  await view.click();
  const editor = page.getByRole('textbox', { name: 'Edit content' });
  await expect(editor).toBeVisible();
  await editor.click();
  return editor;
}

/** Select all editor content and delete it. */
async function clearEditor(page: Page): Promise<void> {
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.press('Delete');
}

test.describe('Journal Markdown Editor', () => {
  test('renders markdown content in the detail view', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const content = await openJournalWithContent(
      page,
      testCleanup,
      '# Big heading\n\nSome **bold** words.\n\n- first\n- second'
    );

    // Markdown is rendered as real elements, not literal syntax.
    await expect(
      content.getByRole('heading', { level: 1, name: 'Big heading' })
    ).toBeVisible();
    await expect(content.locator('strong', { hasText: 'bold' })).toBeVisible();
    await expect(content.locator('li')).toHaveCount(2);
    await expect(content).not.toContainText('# Big heading');
  });

  test('does not execute embedded scripts (XSS)', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const content = await openJournalWithContent(
      page,
      testCleanup,
      'Before <script>window.__xssExecuted = true;</script><img src=x onerror="window.__xssExecuted = true"> After'
    );

    // The raw HTML must not execute and must not become a live <img> node.
    const xssExecuted = await page.evaluate(
      () => (window as unknown as { __xssExecuted?: boolean }).__xssExecuted
    );
    expect(xssExecuted).toBeUndefined();
    await expect(content.locator('img')).toHaveCount(0);
    await expect(content).toContainText('Before');
    await expect(content).toContainText('After');
  });

  test('formats text live as you type in the inline editor', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const content = await openJournalWithContent(
      page,
      testCleanup,
      'original content'
    );

    const editor = await openInlineEditor(page, content);
    await clearEditor(page);

    // Type markdown that the editor formats live via input rules.
    await editor.pressSequentially('# My Title', { delay: TYPE_DELAY });
    await page.keyboard.press('Enter');
    await editor.pressSequentially('Some **strong** text', {
      delay: TYPE_DELAY,
    });

    // The raw markdown delimiters are gone — real formatting is shown.
    await expect(editor.locator('h1')).toHaveText('My Title');
    await expect(editor.locator('strong')).toHaveText('strong');

    // Save and verify the rendered markdown persists in the view.
    await page.getByTestId('journal-content-save').click();
    await expect(
      content.getByRole('heading', { level: 1, name: 'My Title' })
    ).toBeVisible();
    await expect(content.locator('strong')).toHaveText('strong');
    await expect(content).not.toContainText('original content');
  });

  test('bold toolbar button formats the selection', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const content = await openJournalWithContent(
      page,
      testCleanup,
      'plain words'
    );

    const editor = await openInlineEditor(page, content);
    await page.keyboard.press('ControlOrMeta+A');
    await page.getByRole('button', { name: 'Bold' }).click();

    await expect(editor.locator('strong')).toHaveText('plain words');

    await page.getByTestId('journal-content-save').click();
    await expect(content.locator('strong')).toHaveText('plain words');
  });

  test('creates a journal with markdown via the create form', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    await page.goto('/journals/new');
    await expect(page.locator('main, [role="main"]').first()).toBeVisible();

    await page.getByLabel(/title/i).fill(`Markdown Create ${Date.now()}`);
    await page.getByLabel(/^note$/i).check();

    const editor = page.getByRole('textbox', { name: 'Content' });
    await editor.click();
    await editor.pressSequentially('## Section', { delay: TYPE_DELAY });
    await page.keyboard.press('Enter');
    await editor.pressSequentially('A **key** point', { delay: TYPE_DELAY });

    // Live formatting inside the create form's editor.
    await expect(editor.locator('h2')).toHaveText('Section');
    await expect(editor.locator('strong')).toHaveText('key');

    await page.getByRole('button', { name: /create journal/i }).click();

    // Rendered markdown appears on the resulting detail page.
    const content = page.getByTestId('journal-content');
    await expect(
      content.getByRole('heading', { level: 2, name: 'Section' })
    ).toBeVisible();
    await expect(content.locator('strong')).toHaveText('key');
  });
});
