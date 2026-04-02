import { test, expect } from './fixtures';
import { FRONTEND_TEST_URL } from './utils/frontend-test-config';

// Helper to create a parent journal via the UI
async function createParentJournal(
  page: any,
  titlePrefix: string,
  content: string
) {
  const parentTitle = `${titlePrefix} - ${Date.now()}`;
  await page.goto('/journals/new');
  await expect(page.locator('main, [role="main"]').first()).toBeVisible();

  await page.getByLabel(/title/i).fill(parentTitle);
  await page.getByLabel(/content/i).fill(content);

  const parentResponsePromise = page.waitForResponse(
    (response: any) =>
      response.url().includes('/api/journals') &&
      response.request().method() === 'POST' &&
      response.status() === 201
  );

  const createButton = page.getByRole('button', { name: /create journal/i });
  await expect(createButton).toBeEnabled();
  await createButton.click();
  await parentResponsePromise;

  // Wait for redirect to detail page
  await page.waitForURL(/\/journals\/\d+/);
  const parentUrl = page.url();
  const match = parentUrl.match(/\/journals\/(\d+)/);
  expect(match).not.toBeNull();
  const parentId = match![1];

  return { parentTitle, parentId };
}

// Helper to verify the breadcrumb and children list rendering
async function verifyHierarchyLinks(
  page: any,
  childTitle: string,
  parentTitle: string,
  parentId: string
) {
  // Verify child detail page shows breadcrumb to parent
  await page.waitForURL(/\/journals\/\d+/);
  await expect(
    page.getByRole('heading', { name: childTitle, exact: true }).first()
  ).toBeVisible();

  const parentLink = page.getByTestId('parent-link');
  await expect(parentLink).toBeVisible();
  await expect(parentLink).toHaveText(parentTitle);
  await expect(parentLink).toHaveAttribute('href', `/journals/${parentId}`);

  // Click parent breadcrumb to verify navigation back to parent
  await parentLink.click();
  await page.waitForURL(/\/journals\/\d+/);
  await expect(
    page.getByRole('heading', { name: parentTitle, exact: true }).first()
  ).toBeVisible();

  // Verify child journal appears in parent's children list
  const childLink = page.getByRole('link', { name: childTitle });
  await expect(childLink).toBeVisible();
}

// Helper to create a journal via API to avoid code duplication
async function createJournalViaApi(
  request: any,
  title: string,
  content: string
) {
  const response = await request.post(`${FRONTEND_TEST_URL}/api/journals`, {
    data: {
      data: {
        type: 'journals',
        attributes: {
          title,
          content,
          event_date_range: {
            start: new Date().toISOString(),
            end: new Date().toISOString(),
          },
        },
      },
    },
  });
  expect(response.ok()).toBeTruthy();
  const data = await response.json();
  return data.data.id;
}

test.describe('Journal Hierarchy', () => {
  // Helper to ensure clean slate
  test.afterEach(async ({ request }) => {
    try {
      // Find all journals starting with 'E2E Hierarchy' and delete them using API
      const searchResponse = await request.get(
        `${FRONTEND_TEST_URL}/api/journals?search=E2E Hierarchy`
      );
      if (searchResponse.ok()) {
        const body = await searchResponse.json();
        for (const journal of body.data) {
          await request.delete(
            `${FRONTEND_TEST_URL}/api/journals/${journal.id}`
          );
        }
      }
    } catch (e) {
      console.debug('Cleanup failed:', e);
    }
  });

  test('should create a child journal and display the parent reference', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    // 1. Create the parent journal
    const { parentTitle, parentId } = await createParentJournal(
      page,
      'E2E Hierarchy Parent',
      'This is the parent journal.'
    );

    // Wait for parent journal to be indexed so the combobox search can find it
    await expect
      .poll(
        async () => {
          const response = await page.request.get(
            `/api/journals/search?q=${encodeURIComponent(parentTitle)}`
          );
          if (!response.ok()) {
            return false;
          }
          const data = await response.json();
          return data.data?.some(
            (j: Record<string, unknown>) => String(j.id) === parentId
          );
        },
        { timeout: 30000 }
      )
      .toBeTruthy();

    // 2. Create the child journal
    const childTitle = `E2E Hierarchy Child - ${Date.now()}`;
    await page.goto('/journals/new');
    await expect(page.locator('main, [role="main"]').first()).toBeVisible();

    await page.getByLabel(/title/i).fill(childTitle);
    await page.getByLabel(/content/i).fill('This is the child journal.');

    // Select parent journal using combobox
    await page.fill(
      'input[placeholder="Search for a parent journal..."]',
      'E2E Hierarchy Parent'
    );

    const parentOption = page.getByRole('option', { name: parentTitle });
    await expect(parentOption).toBeVisible({ timeout: 10000 });
    await parentOption.click();

    const childResponsePromise = page.waitForResponse(
      response =>
        response.url().includes('/api/journals') &&
        response.request().method() === 'POST' &&
        response.status() === 201
    );

    const childCreateButton = page.getByRole('button', {
      name: /create journal/i,
    });
    await expect(childCreateButton).toBeEnabled();
    await childCreateButton.click();
    await childResponsePromise;

    // 3. Verify links
    await verifyHierarchyLinks(page, childTitle, parentTitle, parentId);
  });

  test('should create a child journal from the parent detail page', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    // 1. Create parent journal
    const { parentTitle, parentId } = await createParentJournal(
      page,
      'E2E Hierarchy Detail Parent',
      'Parent for detail-page child creation test.'
    );

    // 2. Click "Add Child" link from the detail page
    const addChildLink = page.getByRole('link', { name: /add child/i });
    await expect(addChildLink).toBeVisible();
    await addChildLink.click();

    // 3. Verify navigated to create form with parentId in URL
    await page.waitForURL(/\/journals\/new\?parentId=/);
    expect(page.url()).toContain(`parentId=${parentId}`);

    // 4. Verify the parent journal is pre-selected
    const parentInput = page.locator(
      'input[placeholder="Search for a parent journal..."]'
    );
    await expect(parentInput).toHaveValue(parentTitle, { timeout: 10000 });

    // 5. Fill child journal details and submit
    const childTitle = `E2E Hierarchy Detail Child - ${Date.now()}`;
    await page.getByLabel(/title/i).fill(childTitle);
    await page
      .getByLabel(/content/i)
      .fill('Child created from parent detail page.');

    const childResponsePromise = page.waitForResponse(
      response =>
        response.url().includes('/api/journals') &&
        response.request().method() === 'POST' &&
        response.status() === 201
    );

    const submitButton = page.getByRole('button', { name: /create journal/i });
    await expect(submitButton).toBeEnabled();
    await submitButton.click();
    await childResponsePromise;

    // 6. Verify links
    await verifyHierarchyLinks(page, childTitle, parentTitle, parentId);
  });

  test('should add an existing journal as a child from parent detail page', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const timestamp = Date.now();

    // 1. Create two independent journals via API
    const parentTitle = `E2E Hierarchy AddExisting Parent - ${timestamp}`;
    const childTitle = `E2E Hierarchy AddExisting Child - ${timestamp}`;

    const parentId = await createJournalViaApi(
      authenticatedPage.request,
      parentTitle,
      'Parent journal for add-existing test.'
    );
    await createJournalViaApi(
      authenticatedPage.request,
      childTitle,
      'Child journal for add-existing test.'
    );

    // 2. Navigate to the parent journal detail page
    await page.goto(`/journals/${parentId}`);
    await expect(
      page.getByRole('heading', { name: parentTitle, exact: true }).first()
    ).toBeVisible();

    // 3. Click "Add Existing" button
    const addExistingButton = page.getByRole('button', {
      name: /add existing/i,
    });
    await expect(addExistingButton).toBeVisible();
    await addExistingButton.click();

    // 4. Search for the child journal
    const searchInput = page.locator('#add-existing-child-search');
    await expect(searchInput).toBeVisible();
    await searchInput.fill(childTitle);

    // 5. Wait for and select the journal from results
    const childOption = page
      .getByRole('option', { name: new RegExp(childTitle.slice(0, 30)) })
      .first();
    await expect(childOption).toBeVisible({ timeout: 10000 });
    await childOption.click();

    // 6. Wait for the PATCH request to complete
    await page.waitForResponse(
      response =>
        response.url().includes('/api/journals/') &&
        response.request().method() === 'PATCH' &&
        response.status() === 200
    );

    // 7. Verify the child now appears in the children list
    await page.reload();
    await expect(
      page.getByRole('heading', { name: parentTitle, exact: true }).first()
    ).toBeVisible();

    const childLink = page
      .getByTestId('children-list')
      .getByRole('link', { name: new RegExp(childTitle.slice(0, 30)) });
    await expect(childLink).toBeVisible({ timeout: 10000 });
  });

  test('should set parent from child detail page using parent selector', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    const timestamp = Date.now();

    // 1. Create two independent journals via API
    const parentTitle = `E2E Hierarchy SetParent Parent - ${timestamp}`;
    const childTitle = `E2E Hierarchy SetParent Child - ${timestamp}`;

    await createJournalViaApi(
      authenticatedPage.request,
      parentTitle,
      'Parent for set-parent test.'
    );
    const childId = await createJournalViaApi(
      authenticatedPage.request,
      childTitle,
      'Child for set-parent test.'
    );

    // 2. Navigate to the child journal detail page
    await page.goto(`/journals/${childId}`);
    await expect(
      page.getByRole('heading', { name: childTitle, exact: true }).first()
    ).toBeVisible();

    // 3. Click "Set Parent" button
    const setParentButton = page.getByRole('button', {
      name: /set parent/i,
    });
    await expect(setParentButton).toBeVisible();
    await setParentButton.click();

    // 4. Search for the parent journal
    const parentSearchInput = page.locator('#parent-journal-search');
    await expect(parentSearchInput).toBeVisible();
    await parentSearchInput.fill(parentTitle);

    // 5. Select the parent from search results
    const parentOption = page
      .getByRole('option', { name: new RegExp(parentTitle.slice(0, 30)) })
      .first();
    await expect(parentOption).toBeVisible({ timeout: 10000 });
    await parentOption.click();

    // 6. Wait for PATCH to complete
    await page.waitForResponse(
      response =>
        response.url().includes('/api/journals/') &&
        response.request().method() === 'PATCH' &&
        response.status() === 200
    );

    // 7. Verify breadcrumb shows the parent link
    await page.reload();
    await expect(
      page.getByRole('heading', { name: childTitle, exact: true }).first()
    ).toBeVisible();

    const parentLink = page.getByTestId('parent-link');
    await expect(parentLink).toBeVisible({ timeout: 10000 });
    await expect(parentLink).toHaveText(parentTitle);
  });
});
