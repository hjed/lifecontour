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
  // Note: markdown-to-element rendering (headings, emphasis, lists, GFM) and
  // XSS sanitisation (no live <script>/<img onerror> nodes, no event-handler
  // attributes) are unit-tested in MarkdownRenderer.test.tsx. The tests below
  // stay as e2e because they assert computed CSS, real typing through
  // ProseMirror input rules, or the persistence round-trip — none of which
  // jsdom can exercise.

  test('applies typography styling to the rendered markdown', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const content = await openJournalWithContent(
      page,
      testCleanup,
      '# Big heading\n\n- first\n- second'
    );

    // The typography plugin must actually style the semantic elements —
    // without it preflight leaves headings at inherited weight and lists
    // without bullets, so markdown looks like plain text.
    const heading = content.getByRole('heading', { level: 1 });
    await expect(heading).toHaveCSS('font-weight', '800');
    await expect(content.locator('ul')).toHaveCSS('list-style-type', 'disc');
  });

  test('prose text follows the class-based dark theme', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const content = await openJournalWithContent(
      page,
      testCleanup,
      '# Big heading\n\nBody text.'
    );

    // Prose colors come from the app's theme tokens, so toggling the `.dark`
    // class must restyle the rendered markdown (media-query-based
    // `prose-invert` would ignore the in-app toggle).
    const heading = content.getByRole('heading', { level: 1 });
    const lightColor = await heading.evaluate(el => getComputedStyle(el).color);
    await page.getByTestId('theme-toggle').click();
    // Guard that the click actually engaged the class-based toggle — if the
    // header ever swaps to the dropdown ThemeToggle (first click only opens a
    // menu), this fails loudly instead of timing out on the color assertion.
    await expect(page.locator('html')).toHaveClass(/dark/);
    await expect(heading).not.toHaveCSS('color', lightColor);
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

  // The toolbar's wiring is unit-tested in MarkdownEditor.test.tsx, but that
  // test mocks Tiptap (its command chain is a no-op), so only this browser
  // test proves a toolbar command actually formats a real ProseMirror
  // selection.
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
