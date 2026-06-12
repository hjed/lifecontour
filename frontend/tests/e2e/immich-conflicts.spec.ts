/**
 * E2E tests for Immich conflict resolution UI.
 *
 * These tests stub all API responses to deterministically verify the
 * conflict resolution section appears, lists conflicts, and resolves
 * them by linking to an existing contact or creating a new one.
 */

import { expect, test } from './fixtures';

function json(data: unknown) {
  return {
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  };
}

const IMMICH_CONNECTED_INTEGRATION = {
  id: 'immich',
  type: 'integration',
  attributes: {
    name: 'Immich',
    status: 'connected',
    capabilities: ['contacts_sync', 'album_sync'],
    sync_summary: {
      last_sync_time: '2026-01-01T00:00:00Z',
      sync_count: 10,
      error_count: 0,
    },
    needs_reauth: false,
    needs_reconsent: false,
  },
};

const SAMPLE_CONFLICTS = [
  {
    id: '1',
    type: 'immich-conflict',
    attributes: {
      externalEntityId: 'person-abc-123',
      externalEntityName: 'John Smith',
      candidateContactIds: [10, 20],
      candidateContacts: [
        { id: 10, name: 'Johnny Smith', photoUrl: null },
        { id: 20, name: 'John Smithson', photoUrl: null },
      ],
      status: 'unresolved',
      createdAt: '2026-01-15T10:00:00Z',
    },
  },
  {
    id: '2',
    type: 'immich-conflict',
    attributes: {
      externalEntityId: 'person-def-456',
      externalEntityName: 'Jane Doe',
      candidateContactIds: [30],
      candidateContacts: [{ id: 30, name: 'Jane Doe', photoUrl: null }],
      status: 'unresolved',
      createdAt: '2026-01-15T11:00:00Z',
    },
  },
];

/**
 * Shared API route stubs for Immich connected state.
 */
async function setupConnectedRoutes(page: import('@playwright/test').Page) {
  // Health endpoint
  await page.route('**/api/integrations/health', route =>
    route.fulfill(
      json({
        data: {
          id: 'integrations',
          type: 'integration-health',
          attributes: {
            overall: 'healthy',
            lastChecked: new Date().toISOString(),
            redis: { status: 'healthy', latency: 1, lastSeen: null },
            worker: { status: 'healthy', latency: 1, lastSeen: null },
          },
        },
      })
    )
  );

  // Integration list — immich connected
  await page.route('**/api/integrations', route => {
    const url = new URL(route.request().url());
    if (url.pathname !== '/api/integrations') {
      return route.fallback();
    }

    return route.fulfill(
      json({
        data: [IMMICH_CONNECTED_INTEGRATION],
      })
    );
  });

  // Sync history stubs
  await page.route('**/api/integrations/*/sync-history**', route =>
    route.fulfill(
      json({
        data: [],
        meta: { total: 0, page: 1, pageSize: 5 },
      })
    )
  );
}

test.describe('Immich Conflict Resolution', () => {
  test('conflict resolution section is visible when conflicts exist', async ({
    authenticatedPage,
  }) => {
    await setupConnectedRoutes(authenticatedPage);

    // Stub conflicts API — return two unresolved conflicts
    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts',
      route => {
        if (route.request().method() !== 'GET') return route.fallback();
        return route.fulfill(json({ data: SAMPLE_CONFLICTS }));
      }
    );

    await authenticatedPage.goto('/integrations');

    // Verify the conflict section is visible
    const conflictsSection = authenticatedPage.locator(
      '[data-testid="immich-conflicts-section"]'
    );
    await expect(conflictsSection).toBeVisible();

    // Verify section heading shows correct count
    await expect(conflictsSection).toContainText('Synchronisation Conflicts');
    // Verify the count badge exists in the heading area
    await expect(
      conflictsSection.locator('h3').getByText('2', { exact: true })
    ).toBeVisible();

    // Verify both conflict items are rendered
    await expect(
      authenticatedPage.locator('[data-testid="conflict-item-1"]')
    ).toBeVisible();
    await expect(
      authenticatedPage.locator('[data-testid="conflict-item-2"]')
    ).toBeVisible();

    // Verify conflict details are shown
    await expect(
      authenticatedPage.locator('[data-testid="conflict-item-1"]')
    ).toContainText('John Smith');
    await expect(
      authenticatedPage.locator('[data-testid="conflict-item-2"]')
    ).toContainText('Jane Doe');
  });

  test('conflict resolution section is hidden when no conflicts', async ({
    authenticatedPage,
  }) => {
    await setupConnectedRoutes(authenticatedPage);

    // Stub conflicts API — return empty list
    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts',
      route => {
        if (route.request().method() !== 'GET') return route.fallback();
        return route.fulfill(json({ data: [] }));
      }
    );

    // Navigate and wait for the conflicts API to actually respond (prevents
    // false positive from the loading state where the component returns null)
    await Promise.all([
      authenticatedPage.waitForResponse(
        resp =>
          resp.url().includes('/immich/conflicts') &&
          resp.request().method() === 'GET'
      ),
      authenticatedPage.goto('/integrations'),
    ]);

    // Wait for the panel to render
    await expect(
      authenticatedPage.locator('[data-testid="integration-panel-immich"]')
    ).toBeVisible();

    // The conflicts section should not be rendered at all
    await expect(
      authenticatedPage.locator('[data-testid="immich-conflicts-section"]')
    ).toBeHidden();
  });

  test('can link conflict to existing contact', async ({
    authenticatedPage,
  }) => {
    await setupConnectedRoutes(authenticatedPage);

    // Stub initial conflicts (two conflicts)
    let conflictsData = [...SAMPLE_CONFLICTS];
    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts',
      route => {
        if (route.request().method() !== 'GET') return route.fallback();
        return route.fulfill(json({ data: conflictsData }));
      }
    );

    // Stub resolve endpoint
    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts/1/resolve',
      route => {
        if (route.request().method() !== 'POST') return route.fallback();

        // After resolving, remove the first conflict from the list
        conflictsData = conflictsData.filter(c => c.id !== '1');

        return route.fulfill(
          json({
            data: {
              id: '1',
              type: 'immich-conflict',
              attributes: {
                ...SAMPLE_CONFLICTS[0].attributes,
                status: 'resolved',
              },
            },
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    // Wait for conflicts to appear
    const conflictItem = authenticatedPage.locator(
      '[data-testid="conflict-item-1"]'
    );
    await expect(conflictItem).toBeVisible();

    // Select a candidate contact
    const candidateButton = authenticatedPage.locator(
      '[data-testid="conflict-1-candidate-10"]'
    );
    await expect(candidateButton).toBeVisible();
    await candidateButton.click();

    // Verify the button is selected (aria-pressed)
    await expect(candidateButton).toHaveAttribute('aria-pressed', 'true');

    // Click the Link button and wait for the mutation + refetch
    const linkButton = authenticatedPage.locator(
      '[data-testid="conflict-link-button-1"]'
    );
    await expect(linkButton).toBeEnabled();

    await Promise.all([
      authenticatedPage.waitForResponse(
        resp =>
          resp.url().includes('/conflicts/1/resolve') &&
          resp.request().method() === 'POST'
      ),
      authenticatedPage.waitForResponse(
        resp =>
          resp.url().includes('/immich/conflicts') &&
          resp.request().method() === 'GET'
      ),
      linkButton.click(),
    ]);

    // After resolution, the first conflict should disappear
    await expect(conflictItem).toBeHidden();

    // Second conflict should still be visible
    await expect(
      authenticatedPage.locator('[data-testid="conflict-item-2"]')
    ).toBeVisible();
  });

  test('can create new contact from conflict', async ({
    authenticatedPage,
  }) => {
    await setupConnectedRoutes(authenticatedPage);

    // Stub conflicts — single conflict
    let conflictsData = [SAMPLE_CONFLICTS[1]];
    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts',
      route => {
        if (route.request().method() !== 'GET') return route.fallback();
        return route.fulfill(json({ data: conflictsData }));
      }
    );

    // Stub resolve endpoint for conflict #2
    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts/2/resolve',
      route => {
        if (route.request().method() !== 'POST') return route.fallback();

        // After resolving, empty the list
        conflictsData = [];

        return route.fulfill(
          json({
            data: {
              id: '2',
              type: 'immich-conflict',
              attributes: {
                ...SAMPLE_CONFLICTS[1].attributes,
                status: 'resolved',
              },
            },
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    // Wait for conflict to appear
    const conflictItem = authenticatedPage.locator(
      '[data-testid="conflict-item-2"]'
    );
    await expect(conflictItem).toBeVisible();
    await expect(conflictItem).toContainText('Jane Doe');

    // Click Create New button
    const createButton = authenticatedPage.locator(
      '[data-testid="conflict-create-button-2"]'
    );
    await expect(createButton).toBeVisible();

    await Promise.all([
      authenticatedPage.waitForResponse(
        resp =>
          resp.url().includes('/conflicts/2/resolve') &&
          resp.request().method() === 'POST'
      ),
      authenticatedPage.waitForResponse(
        resp =>
          resp.url().includes('/immich/conflicts') &&
          resp.request().method() === 'GET'
      ),
      createButton.click(),
    ]);

    // After resolution, the conflicts section should disappear entirely
    await expect(
      authenticatedPage.locator('[data-testid="immich-conflicts-section"]')
    ).toBeHidden();
  });

  test('link button is disabled until a candidate is selected', async ({
    authenticatedPage,
  }) => {
    await setupConnectedRoutes(authenticatedPage);

    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts',
      route => {
        if (route.request().method() !== 'GET') return route.fallback();
        return route.fulfill(json({ data: [SAMPLE_CONFLICTS[0]] }));
      }
    );

    await authenticatedPage.goto('/integrations');

    // Wait for conflict to appear
    await expect(
      authenticatedPage.locator('[data-testid="conflict-item-1"]')
    ).toBeVisible();

    // Link button should be disabled initially (no candidate selected)
    const linkButton = authenticatedPage.locator(
      '[data-testid="conflict-link-button-1"]'
    );
    await expect(linkButton).toBeDisabled();

    // Select a candidate
    await authenticatedPage
      .locator('[data-testid="conflict-1-candidate-10"]')
      .click();

    // Now the link button should be enabled
    await expect(linkButton).toBeEnabled();
  });

  test('candidate contacts show and can be toggled', async ({
    authenticatedPage,
  }) => {
    await setupConnectedRoutes(authenticatedPage);

    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts',
      route => {
        if (route.request().method() !== 'GET') return route.fallback();
        return route.fulfill(json({ data: [SAMPLE_CONFLICTS[0]] }));
      }
    );

    await authenticatedPage.goto('/integrations');

    // Wait for conflict to appear
    await expect(
      authenticatedPage.locator('[data-testid="conflict-item-1"]')
    ).toBeVisible();

    // Verify candidate buttons are shown
    const candidate10 = authenticatedPage.locator(
      '[data-testid="conflict-1-candidate-10"]'
    );
    const candidate20 = authenticatedPage.locator(
      '[data-testid="conflict-1-candidate-20"]'
    );
    await expect(candidate10).toBeVisible();
    await expect(candidate20).toBeVisible();

    // Candidate chips show real contact names, not raw IDs
    await expect(candidate10).toHaveText('Johnny Smith');
    await expect(candidate20).toHaveText('John Smithson');

    // Select first candidate
    await candidate10.click();
    await expect(candidate10).toHaveAttribute('aria-pressed', 'true');
    await expect(candidate20).toHaveAttribute('aria-pressed', 'false');

    // Switch to second candidate
    await candidate20.click();
    await expect(candidate20).toHaveAttribute('aria-pressed', 'true');
    await expect(candidate10).toHaveAttribute('aria-pressed', 'false');
  });

  test('can link conflict to a contact found via search', async ({
    authenticatedPage,
  }) => {
    await setupConnectedRoutes(authenticatedPage);

    let conflictsData = [SAMPLE_CONFLICTS[0]];
    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts',
      route => {
        if (route.request().method() !== 'GET') return route.fallback();
        return route.fulfill(json({ data: conflictsData }));
      }
    );

    // Stub the contact search endpoint used by ContactSearchCombobox
    await authenticatedPage.route('**/api/search/contacts**', route => {
      if (route.request().method() !== 'GET') return route.fallback();
      return route.fulfill(
        json({
          data: [
            {
              id: '99',
              type: 'contacts',
              attributes: {
                first_name: 'Sarah',
                last_name: 'Connor',
                nick_name: null,
              },
            },
          ],
        })
      );
    });

    // Stub resolve endpoint and capture the linked contact id
    let resolvedContactId: number | null = null;
    await authenticatedPage.route(
      '**/api/integrations/immich/conflicts/1/resolve',
      async route => {
        if (route.request().method() !== 'POST') return route.fallback();
        const body = route.request().postDataJSON() as {
          action: string;
          contact_id?: number;
        };
        resolvedContactId = body.contact_id ?? null;
        conflictsData = conflictsData.filter(c => c.id !== '1');
        return route.fulfill(
          json({
            data: {
              id: '1',
              type: 'immich-conflict',
              attributes: {
                ...SAMPLE_CONFLICTS[0].attributes,
                status: 'resolved',
              },
            },
          })
        );
      }
    );

    await authenticatedPage.goto('/integrations');

    const conflictItem = authenticatedPage.locator(
      '[data-testid="conflict-item-1"]'
    );
    await expect(conflictItem).toBeVisible();

    // Search for a contact that is not one of the auto-detected candidates
    const searchInput = authenticatedPage.locator('#conflict-1-search');
    await searchInput.fill('Sarah');

    const searchResult = authenticatedPage.getByText('Sarah Connor', {
      exact: true,
    });
    await expect(searchResult).toBeVisible();
    await searchResult.click();

    // The selected contact is reflected in the UI
    await expect(
      authenticatedPage.locator('[data-testid="conflict-1-selected-search"]')
    ).toContainText('Sarah Connor');

    // Link resolves the conflict with the searched contact id
    const linkButton = authenticatedPage.locator(
      '[data-testid="conflict-link-button-1"]'
    );
    await expect(linkButton).toBeEnabled();

    await Promise.all([
      authenticatedPage.waitForResponse(
        resp =>
          resp.url().includes('/conflicts/1/resolve') &&
          resp.request().method() === 'POST'
      ),
      linkButton.click(),
    ]);

    expect(resolvedContactId).toBe(99);
    await expect(conflictItem).toBeHidden();
  });
});
