/**
 * E2E Tests for Journal Creation UI Flow
 *
 * Tests the creation of journals through the UI with different types and inline editors.
 */

import { test, expect } from './fixtures';

import { type Locator, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Shared helpers — extracted to eliminate per-test duplication flagged by
// SonarQube. Each helper encapsulates a repeated sequence of actions.
// ---------------------------------------------------------------------------

/** Navigate to /journals/new and wait for the page to be fully loaded. */
async function navigateToNewJournal(page: Page) {
  await page.goto('/journals/new');
  await expect(page.locator('main, [role="main"]').first()).toBeVisible();
}

/** Fill the common journal fields and select the requested type. */
async function fillJournalBasics(
  page: Page,
  opts: { title: string; content: string; typeLabelRegex: RegExp }
) {
  await page.getByLabel(/title/i).fill(opts.title);
  await page.getByLabel(/content/i).fill(opts.content);
  await page.getByLabel(opts.typeLabelRegex).check();
}

/**
 * Fill common fields, select the given journal type, and submit the creation form.
 * Returns after the form has been submitted (does NOT wait for redirect).
 */
async function fillAndSubmitJournal(
  page: Page,
  opts: { title: string; content: string; typeLabelRegex: RegExp }
) {
  await fillJournalBasics(page, opts);
  await page.getByRole('button', { name: /create journal/i }).click();
}

// Removed createRoute and selectRouteInEditor as they are obsolete
// Routes are now created by uploading GPX files during journal creation

/** Assert the selected type panel and its dependency badges in the create form. */
async function assertSelectedTypeDependencies(
  page: Page,
  typeTestId: string,
  dependencyTypeTestIds: readonly string[]
) {
  await expect(
    page.locator(`[data-testid="selected-type-panel-${typeTestId}"]`)
  ).toBeVisible();

  for (const dependencyTypeTestId of dependencyTypeTestIds) {
    await expect(
      page.locator(
        `[data-testid="selected-type-dependency-${typeTestId}-${dependencyTypeTestId}"]`
      )
    ).toBeVisible();
  }
}

/** Assert the expected set of attached type badges on the journal detail page. */
async function assertAttachedTypeBadges(page: Page, types: readonly string[]) {
  for (const type of types) {
    await expect(page.getByTestId(`manage-type-${type}`)).toBeVisible();
  }
}

/**
 * Wait for redirect to a journal detail page and assert the given type badge is visible.
 * Returns the final URL so callers can extract the journal ID if needed.
 */
async function awaitCreationAndAssertBadge(
  page: Page,
  badgeTestId: string
): Promise<string> {
  await page.waitForURL(/\/journals\/\d+/);
  await expect(page.getByTestId(badgeTestId)).toBeVisible();
  return page.url();
}

interface ComplexRouteBackedJournalOptions {
  readonly gpxTrackName: string;
  readonly journal: {
    readonly title: string;
    readonly content: string;
    readonly typeLabelRegex: RegExp;
  };
  readonly selectedTypeTestId: string;
  readonly dependencyTypeTestIds: readonly string[];
  readonly editorTestId: string;
  readonly badgeTestId: string;
  readonly attachedTypes: readonly string[];
  readonly typeSectionTriggerTestId: string;
  readonly summaryTestId: string;
  readonly fillTypeFields: (args: {
    page: Page;
    editor: Locator;
  }) => Promise<void>;
  readonly assertSummary: (args: { summary: Locator }) => Promise<void>;
}

async function createRouteBackedComplexJournal(
  page: Page,
  opts: ComplexRouteBackedJournalOptions
) {
  await navigateToNewJournal(page);
  await fillJournalBasics(page, opts.journal);
  await assertSelectedTypeDependencies(
    page,
    opts.selectedTypeTestId,
    opts.dependencyTypeTestIds
  );

  const editor = page.getByTestId(opts.editorTestId);
  await expect(editor).toBeVisible();

  await expect(page.getByTestId('fitness-type-editor')).toBeVisible();

  const gpxContent = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk><trkseg><trkpt lat="-33.8" lon="151.2"></trkpt></trkseg></trk>
</gpx>`;
  await page.getByTestId('gpx-multi-file-input').setInputFiles({
    name: `${opts.gpxTrackName}.gpx`,
    mimeType: 'application/gpx+xml',
    buffer: Buffer.from(gpxContent),
  });

  await opts.fillTypeFields({ page, editor });

  await page.getByRole('button', { name: /create journal/i }).click();

  await awaitCreationAndAssertBadge(page, opts.badgeTestId);
  await assertAttachedTypeBadges(page, opts.attachedTypes);

  await page.getByTestId(opts.typeSectionTriggerTestId).click();

  const summary = page.getByTestId(opts.summaryTestId);
  await expect(summary).toBeVisible();
  await opts.assertSummary({ summary });

  // Also verify that the GPX map rendered
  await page.getByTestId('type-section-trigger-fitness').click();
  // Map renders on the journal detail view AFTER submission
  await expect(page.getByTestId('gpx-track-display')).toBeVisible();
  await expect(page.locator('.leaflet-container')).toBeVisible();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Journal Creation UI Flow', () => {
  test.beforeEach(async ({ authenticatedPage }) => {
    const debugE2E = !!process.env.DEBUG_E2E;

    authenticatedPage.on('pageerror', exception => {
      console.log(
        `[Browser pageerror] ${exception.message} \n ${exception.stack}`
      );
    });

    authenticatedPage.on('console', msg => {
      const type = msg.type();
      // In normal runs, only log browser console errors/warnings to keep CI output manageable.
      // Set DEBUG_E2E=1 to log all console messages for deeper debugging.
      if (!debugE2E && type !== 'error' && type !== 'warning') {
        return;
      }
      console.log(`[Browser Console] ${type}: ${msg.text()}`);
    });
    // Log API errors for journals to surface backend validation failures
    authenticatedPage.on('response', async response => {
      if (
        response.url().includes('/api/journals') &&
        response.request().method() === 'POST'
      ) {
        if (!response.ok()) {
          console.log(`[API Response] ${response.status()}`);
          try {
            const data = await response.json();
            console.log('[API JSON Body Error]', JSON.stringify(data, null, 2));
          } catch (e) {
            console.log('[API Body Parsing Error]', e);
          }
        }
      }
    });
  });

  test('should create a MOOD_RATING journal with default slider values', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    const title = `Mood Check ${Date.now()}`;
    await page.getByLabel(/title/i).fill(title);
    await page.getByLabel(/content/i).fill('Feeling neutral today.');
    await page.getByLabel(/^mood rating$/i).check();

    // Assert the editor is visible and defaults to 5 BEFORE submitting,
    // so navigation cannot race with these assertions.
    await expect(page.getByTestId('mood-rating-type-editor')).toBeVisible();
    await expect(page.getByTestId('mood-value-display')).toHaveText('5');

    await page.getByRole('button', { name: /create journal/i }).click();

    await awaitCreationAndAssertBadge(page, 'manage-type-mood_rating');

    // The type section is collapsed by default on the detail page.
    // We must expand it to assert on the type editors/displays inside it.
    await page.getByTestId('type-section-trigger-mood_rating').click();

    // Verify the persisted mood value (default 5) is shown on the detail page
    await expect(page.getByTestId('mood-value-display')).toHaveText('5');
  });

  test('should create a PLAN journal', async ({ authenticatedPage }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Trip Plan ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Plan for upcoming trip.');
    await page.getByLabel(/^plan$/i).check();

    // Verify plan editor is visible before adding a document
    await expect(page.getByTestId('plan-type-editor')).toBeVisible();

    await page.getByTestId('add-document-button').waitFor({ state: 'visible' });
    await page.getByTestId('add-document-button').click();
    await page.getByTestId('document-url-0').waitFor({ state: 'visible' });
    await page.getByTestId('document-url-0').fill('https://example.com/plan');
    await page.getByTestId('document-title-0').fill('Itinerary');

    // Web-first assertion avoids a race condition between Playwright fill and React Hook Form validation
    await expect(page.getByTestId('document-url-0')).toHaveValue(
      'https://example.com/plan'
    );
    await expect(page.getByTestId('document-title-0')).toHaveValue('Itinerary');

    await page.getByRole('button', { name: /create journal/i }).click();

    await awaitCreationAndAssertBadge(page, 'manage-type-plan');

    // The type section is collapsed by default on the detail page.
    await page.getByTestId('type-section-trigger-plan').click();

    // Verify the document was persisted and rendered on the detail page
    await expect(page.getByTestId('document-url-0')).toHaveValue(
      'https://example.com/plan'
    );
    await expect(page.getByTestId('document-title-0')).toHaveValue('Itinerary');
  });

  test('should create an EVENT journal with calendar info', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    // Create a physical calendar via API to satisfy the foreign key constraint
    const calendarName = `E2E Cal ${Date.now()}`;
    const calendarRes = await page.request.post('/api/calendars', {
      data: {
        data: {
          type: 'calendars',
          attributes: {
            name: calendarName,
            description: 'Created by e2e test',
          },
        },
      },
    });
    expect(calendarRes.ok()).toBeTruthy();
    const calendarJson = await calendarRes.json();
    expect(calendarJson.data).toBeDefined();
    expect(calendarJson.data.id).toBeDefined();

    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Event ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Event details.');
    await page.getByLabel(/^event$/i).check();

    await expect(page.getByTestId('event-type-editor')).toBeVisible();
    await page
      .getByRole('checkbox', { name: /all-day event/i })
      .waitFor({ state: 'visible' });
    await page.getByTestId('calendar-id-input').click();
    const calendarOption = page.getByRole('option', { name: calendarName });
    await expect(calendarOption).toBeVisible({ timeout: 10000 });
    await calendarOption.click();

    // Check all-day to avoid Start/End time validation unless we want to fill them
    await page.getByRole('checkbox', { name: /all-day event/i }).check();

    await page.getByRole('button', { name: /create journal/i }).click();
    await awaitCreationAndAssertBadge(page, 'manage-type-event');
  });

  test('should create a TRAVEL journal with locations', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await fillAndSubmitJournal(page, {
      title: `Trip ${Date.now()}`,
      content: 'Trip details regarding flights and accommodation.',
      typeLabelRegex: /^travel$/i,
    });

    // fillAndSubmitJournal already clicked Create Journal; wait for the redirect
    // and verify the travel type badge appears on the detail page.
    await awaitCreationAndAssertBadge(page, 'manage-type-travel');
  });

  test('should create a PHOTO_ALBUM journal with immich ID', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Photos ${Date.now()}`);
    await page
      .getByLabel(/content/i)
      .fill('A collection of photos from the recent trip.');
    await page.getByLabel(/^photo album$/i).check();

    await expect(page.getByTestId('photo-album-type-editor')).toBeVisible();
    await page
      .getByTestId('immich-album-id-input')
      .waitFor({ state: 'visible' });
    await page
      .getByTestId('immich-album-id-input')
      .fill('223e4567-e89b-12d3-a456-426614174001');

    await page.getByRole('button', { name: /create journal/i }).click();
    await awaitCreationAndAssertBadge(page, 'manage-type-photo_album');
  });

  test('should create a FITNESS journal and verify ActivityStats render', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Run ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Morning 5k run.');

    // Select the FITNESS type
    await page.getByLabel(/^fitness$/i).check();

    // Verify editor is visible
    await expect(page.getByTestId('fitness-type-editor')).toBeVisible();

    // Fill fitness stats
    await page.getByTestId('distance-input').fill('5000');
    await page.getByTestId('duration-input').fill('1500'); // 25 minutes
    await page.getByTestId('hr-avg-input').fill('155');

    // Upload a mock GPX file to trigger Map rendering
    const gpxContent = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk>
    <trkseg>
      <trkpt lat="-33.8688" lon="151.2093"><ele>10</ele><time>2026-01-01T00:00:00Z</time></trkpt>
      <trkpt lat="-33.8690" lon="151.2095"><ele>12</ele><time>2026-01-01T00:00:10Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>`;

    await page.getByTestId('gpx-multi-file-input').setInputFiles({
      name: 'test-track.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from(gpxContent),
    });

    await page.getByRole('button', { name: /create journal/i }).click();

    // Verify redirect and badge
    await awaitCreationAndAssertBadge(page, 'manage-type-fitness');

    // Expand type section
    await page.getByTestId('type-section-trigger-fitness').click();

    // Verify stats are rendered in read-only mode by ActivityStats
    await expect(page.getByTestId('activity-stats-grid')).toBeVisible();
    await expect(page.getByTestId('stat-distance')).toHaveText('5.00 km');
    await expect(page.getByTestId('stat-duration')).toHaveText('25:00');
    await expect(page.getByTestId('stat-pace')).toHaveText('5:00 /km');
    await expect(page.getByTestId('stat-hr')).toHaveText('155 bpm');

    // Verify map is rendered
    await expect(page.getByTestId('gpx-track-display')).toBeVisible();
    await expect(page.locator('.leaflet-container')).toBeVisible();
  });

  test('should create an OUTDOOR_ACTIVITY journal and verify fields', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Outdoor Trip ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Great outdoor trip.');
    await page.getByLabel(/^outdoor activity$/i).check();

    await expect(page.getByTestId('outdoor-type-editor')).toBeVisible();

    await page.getByTestId('weather-conditions-input').fill('Sunny, 25C');
    await page.getByTestId('role-input').fill('Lead Climber');
    await page.getByTestId('leadership-role-switch').click();
    await page
      .getByTestId('participant-notes-input')
      .fill('Everyone did well.');

    await page.getByRole('button', { name: /create journal/i }).click();

    await awaitCreationAndAssertBadge(page, 'manage-type-outdoor_activity');
    await page.getByTestId('type-section-trigger-outdoor_activity').click();

    // Verify fields are rendered
    await expect(page.getByText('Sunny, 25C')).toBeVisible();
    await expect(page.getByText(/Lead Climber/)).toBeVisible();
    await expect(page.getByText(/(Leadership)/i)).toBeVisible();
    await expect(page.getByText('Everyone did well.')).toBeVisible();
  });

  test('should create a JOGGING journal and verify fields', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Morning Jog ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Good morning run.');
    await page.getByLabel(/^jogging$/i).check();

    await expect(page.getByTestId('jogging-type-editor')).toBeVisible();

    // Fill pace as 5:30
    await page.getByTestId('pace-input').fill('5:30');

    await page.getByRole('button', { name: /create journal/i }).click();

    await awaitCreationAndAssertBadge(page, 'manage-type-jogging');
    await page.getByTestId('type-section-trigger-jogging').click();

    // Verify pace is rendered
    await expect(page.getByText('5:30 /km')).toBeVisible();
  });

  test('should create a BUSHWALKING journal with a GPX track and verify display', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    await navigateToNewJournal(page);

    await fillJournalBasics(page, {
      title: `Bushwalk With Route ${Date.now()}`,
      content: 'Walk with a planned route.',
      typeLabelRegex: /^bushwalking$/i,
    });

    await expect(page.getByTestId('bushwalking-type-editor')).toBeVisible();
    await expect(page.getByTestId('fitness-type-editor')).toBeVisible();

    const gpxContent = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk><trkseg><trkpt lat="-33.8" lon="151.2"></trkpt></trkseg></trk>
</gpx>`;
    await page.getByTestId('gpx-multi-file-input').setInputFiles({
      name: `E2E_Bushwalk_Track.gpx`,
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from(gpxContent),
    });

    await page.getByRole('button', { name: /create journal/i }).click();

    await awaitCreationAndAssertBadge(page, 'manage-type-bushwalking');
    await page.getByTestId('type-section-trigger-bushwalking').click();
    await page.getByTestId('type-section-trigger-fitness').click();

    // Verify map is rendered showing the uploaded GPX
    await expect(page.getByTestId('gpx-track-display')).toBeVisible();
    await expect(page.locator('.leaflet-container')).toBeVisible();
  });

  test('should create a JOGGING journal with a GPX track and verify display', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    await navigateToNewJournal(page);

    await fillJournalBasics(page, {
      title: `Jog With Route ${Date.now()}`,
      content: 'Run with a planned route.',
      typeLabelRegex: /^jogging$/i,
    });

    await expect(page.getByTestId('jogging-type-editor')).toBeVisible();
    await expect(page.getByTestId('fitness-type-editor')).toBeVisible();

    const gpxContent = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk><trkseg><trkpt lat="-33.8" lon="151.2"></trkpt></trkseg></trk>
</gpx>`;
    await page.getByTestId('gpx-multi-file-input').setInputFiles({
      name: `E2E_Jogging_Track.gpx`,
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from(gpxContent),
    });

    await page.getByRole('button', { name: /create journal/i }).click();

    await awaitCreationAndAssertBadge(page, 'manage-type-jogging');
    await page.getByTestId('type-section-trigger-jogging').click();
    await page.getByTestId('type-section-trigger-fitness').click();

    // Verify route map is displayed in read-only view
    await expect(page.getByTestId('gpx-track-display')).toBeVisible();
    await expect(page.locator('.leaflet-container')).toBeVisible();
  });

  test('should create an ABSEILING_TRIP journal and verify dependencies and summary', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await fillJournalBasics(page, {
      title: `Abseiling Trip ${Date.now()}`,
      content: 'Big descent day with multiple drops.',
      typeLabelRegex: /^abseiling trip$/i,
    });

    await assertSelectedTypeDependencies(page, 'ABSEILING_TRIP', [
      'OUTDOOR_ACTIVITY',
      'FITNESS',
    ]);
    await expect(page.getByTestId('abseiling-trip-type-editor')).toBeVisible();

    // Verify auto-calculation with pitches
    await page.getByTestId('add-pitch-button').click();
    await page.getByTestId('pitch-row-0').getByPlaceholder('Height').fill('40');
    await expect(page.getByTestId('number-of-abseils-input')).toHaveValue('1');
    await expect(page.getByTestId('total-length-input')).toHaveValue('40');

    await page.getByTestId('add-pitch-button').click();
    await page.getByTestId('pitch-row-1').getByPlaceholder('Height').fill('60');
    await expect(page.getByTestId('number-of-abseils-input')).toHaveValue('2');
    await expect(page.getByTestId('total-length-input')).toHaveValue('100');

    // Edit a pitch and verify totals update
    await page.getByTestId('pitch-row-0').getByPlaceholder('Height').fill('50');
    await expect(page.getByTestId('total-length-input')).toHaveValue('110');

    // Manual override
    await page.getByTestId('number-of-abseils-input').fill('4');
    await page.getByTestId('total-length-input').fill('120');

    // Assert that subsequent pitch edits do NOT change the overridden totals
    await page.getByTestId('pitch-row-1').getByPlaceholder('Height').fill('70');
    await expect(page.getByTestId('total-length-input')).toHaveValue('120');
    await expect(page.getByTestId('number-of-abseils-input')).toHaveValue('4');

    await page.getByRole('button', { name: /create journal/i }).click();

    await awaitCreationAndAssertBadge(page, 'manage-type-abseiling_trip');
    await assertAttachedTypeBadges(page, [
      'abseiling_trip',
      'outdoor_activity',
      'fitness',
    ]);

    await page.getByTestId('type-section-trigger-abseiling_trip').click();

    const summary = page.getByTestId('abseiling-trip-summary');
    await expect(summary).toBeVisible();
    await expect(summary).toContainText('4');
    await expect(summary).toContainText('120 m');

    // Verify pitch readonly mode
    const pitchReadOnly = page.getByTestId('pitch-editor-readonly');
    await expect(pitchReadOnly).toBeVisible();
    await expect(pitchReadOnly).toContainText('Pitches (2)');
    await expect(pitchReadOnly).toContainText('50m');
    await expect(pitchReadOnly).toContainText('70m');
  });

  test('should create a CANYONING journal and verify transitive dependencies and summary', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await createRouteBackedComplexJournal(page, {
      gpxTrackName: `E2E_Canyon_Route_${Date.now()}`,
      journal: {
        title: `Canyon Trip ${Date.now()}`,
        content: 'Technical canyon with flowing water.',
        typeLabelRegex: /^canyoning$/i,
      },
      selectedTypeTestId: 'CANYONING',
      dependencyTypeTestIds: [
        'BUSHWALKING',
        'ABSEILING_TRIP',
        'OUTDOOR_ACTIVITY',
        'FITNESS',
      ],
      editorTestId: 'canyoning-type-editor',
      badgeTestId: 'manage-type-canyoning',
      attachedTypes: [
        'canyoning',
        'bushwalking',
        'abseiling_trip',
        'outdoor_activity',
        'fitness',
      ],
      typeSectionTriggerTestId: 'type-section-trigger-canyoning',
      summaryTestId: 'canyoning-summary',
      fillTypeFields: async ({ page: detailPage }) => {
        await detailPage.getByTestId('french-grade-input').fill('v3a2iv**');
        await detailPage
          .getByTestId('water-gauge-name-input')
          .fill('Kowmung Gauge');
        await detailPage.getByTestId('water-gauge-level-input').fill('8');
        await detailPage.getByTestId('vertical-switch').click();
        await detailPage.getByTestId('white-water-switch').click();
      },
      assertSummary: async ({ summary }) => {
        await expect(summary).toContainText('v3a2IV**');
        await expect(summary).toContainText('Kowmung Gauge (8)');
        await expect(summary).toContainText('Vertical');
        await expect(summary).toContainText('White Water');
      },
    });
  });

  test('should pre-populate climbing fields and abseiling pitches when a template is selected', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    // Create a template via API with specific climbing data and pitches
    const templateName = `E2E Climbing Template ${Date.now()}`;
    const templateRes = await page.request.post('/api/templates', {
      data: {
        data: {
          type: 'activity-templates',
          attributes: {
            name: templateName,
            template_type: 'climbing',
            climbing_type: 'sport',
            grade: 21,
            length: 30,
            pitches: [
              { pitch_number: 1, height: 15 },
              { pitch_number: 2, height: 15 },
            ],
          },
        },
      },
    });
    expect(templateRes.ok()).toBeTruthy();

    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Climbing Template ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Journal using template.');
    await page.getByLabel(/^climbing$/i).check();

    await expect(page.getByTestId('climbing-type-editor')).toBeVisible();

    // Select the template by typing to filter and trigger the dropdown
    await page.getByPlaceholder('Select a climbing template...').click();
    await page
      .getByPlaceholder('Select a climbing template...')
      .fill('E2E Climbing');

    // Wait for the option to appear and click it
    const option = page.getByRole('option', {
      name: new RegExp(templateName, 'i'),
    });
    await expect(option).toBeVisible();
    await option.click();

    // Verify Climbing fields are populated
    await expect(page.getByTestId('climbing-grade-input')).toHaveValue('21');
    await expect(page.getByTestId('climbing-length-input')).toHaveValue('30');
    // climbing type combobox
    const climbingTypeCombobox = page
      .getByTestId('climbing-type-editor')
      .getByRole('combobox', { name: /climbing type/i });
    await expect(climbingTypeCombobox).toContainText('sport');

    // Verify Abseiling Trip editor is visible and pitches are populated
    await expect(page.getByTestId('abseiling-trip-type-editor')).toBeVisible();
    await expect(page.getByTestId('number-of-abseils-input')).toHaveValue('2');
    await expect(page.getByTestId('total-length-input')).toHaveValue('30');

    await expect(
      page.getByTestId('pitch-row-0').getByPlaceholder('Height')
    ).toHaveValue('15');
    await expect(
      page.getByTestId('pitch-row-1').getByPlaceholder('Height')
    ).toHaveValue('15');
  });

  test('should create a CLIMBING journal and verify dependencies and summary', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await createRouteBackedComplexJournal(page, {
      gpxTrackName: `E2E_Climbing_Route_${Date.now()}`,
      journal: {
        title: `Climbing Session ${Date.now()}`,
        content: 'Strong day on the wall.',
        typeLabelRegex: /^climbing$/i,
      },
      selectedTypeTestId: 'CLIMBING',
      dependencyTypeTestIds: ['ABSEILING_TRIP', 'OUTDOOR_ACTIVITY', 'FITNESS'],
      editorTestId: 'climbing-type-editor',
      badgeTestId: 'manage-type-climbing',
      attachedTypes: [
        'climbing',
        'abseiling_trip',
        'outdoor_activity',
        'fitness',
      ],
      typeSectionTriggerTestId: 'type-section-trigger-climbing',
      summaryTestId: 'climbing-summary',
      fillTypeFields: async ({ page: detailPage, editor }) => {
        const climbingTypeCombobox = editor.getByRole('combobox', {
          name: /climbing type/i,
        });

        await climbingTypeCombobox.click();
        await detailPage.getByRole('option', { name: 'sport' }).click();
        await expect(climbingTypeCombobox).toContainText('sport');

        await detailPage.getByTestId('climbing-grade-input').fill('18');
        await detailPage.getByTestId('climbing-length-input').fill('30');

        // Verify abseiling pitch editor is available and add a pitch
        await detailPage.getByTestId('add-pitch-button').click();
        await detailPage
          .getByTestId('pitch-row-0')
          .getByPlaceholder('Height')
          .fill('30');
      },
      assertSummary: async ({ summary }) => {
        await expect(summary).toContainText('sport');
        await expect(summary).toContainText('18');
        await expect(summary).toContainText('30 m');
      },
    });
  });

  test('should create a KAYAKING journal (non-white-water) and verify dependencies and summary', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await createRouteBackedComplexJournal(page, {
      gpxTrackName: `E2E_Kayak_Route_${Date.now()}`,
      journal: {
        title: `Kayak Paddle ${Date.now()}`,
        content: 'Cold water paddle with steady flow.',
        typeLabelRegex: /^kayaking$/i,
      },
      selectedTypeTestId: 'KAYAKING',
      dependencyTypeTestIds: ['OUTDOOR_ACTIVITY', 'FITNESS'],
      editorTestId: 'kayaking-type-editor',
      badgeTestId: 'manage-type-kayaking',
      attachedTypes: ['kayaking', 'outdoor_activity', 'fitness'],
      typeSectionTriggerTestId: 'type-section-trigger-kayaking',
      summaryTestId: 'kayaking-summary',
      fillTypeFields: async ({ page: detailPage }) => {
        await detailPage.getByTestId('water-type-input').fill('river');
      },
      assertSummary: async ({ summary }) => {
        await expect(summary).toContainText('river');
      },
    });
  });

  test('should create a KAYAKING journal (white-water) and verify dependencies and summary', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await createRouteBackedComplexJournal(page, {
      gpxTrackName: `E2E_Kayak_WW_Route_${Date.now()}`,
      journal: {
        title: `White Water Kayak ${Date.now()}`,
        content: 'Intense white water session.',
        typeLabelRegex: /^kayaking$/i,
      },
      selectedTypeTestId: 'KAYAKING',
      dependencyTypeTestIds: ['OUTDOOR_ACTIVITY', 'FITNESS'],
      editorTestId: 'kayaking-type-editor',
      badgeTestId: 'manage-type-kayaking',
      attachedTypes: ['kayaking', 'outdoor_activity', 'fitness'],
      typeSectionTriggerTestId: 'type-section-trigger-kayaking',
      summaryTestId: 'kayaking-summary',
      fillTypeFields: async ({ page: detailPage }) => {
        await detailPage.getByTestId('water-type-input').fill('river');
        await detailPage.getByTestId('is-white-water-input').click();
        await detailPage.getByTestId('rapids-grade-input').click();
        await detailPage.getByRole('option', { name: 'Grade III' }).click();
      },
      assertSummary: async ({ summary }) => {
        await expect(summary).toContainText('river');
        await expect(summary).toContainText('Yes');
        await expect(summary).toContainText('III');
      },
    });
  });

  test('should create a CROSS_COUNTRY_SKIING journal and verify dependencies and summary', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await createRouteBackedComplexJournal(page, {
      gpxTrackName: `E2E_Ski_Route_${Date.now()}`,
      journal: {
        title: `XC Ski Tour ${Date.now()}`,
        content: 'Snowy day on groomed tracks.',
        typeLabelRegex: /^cross-country skiing$/i,
      },
      selectedTypeTestId: 'CROSS_COUNTRY_SKIING',
      dependencyTypeTestIds: ['BUSHWALKING', 'OUTDOOR_ACTIVITY', 'FITNESS'],
      editorTestId: 'cross-country-skiing-type-editor',
      badgeTestId: 'manage-type-cross_country_skiing',
      attachedTypes: [
        'cross_country_skiing',
        'bushwalking',
        'outdoor_activity',
        'fitness',
      ],
      typeSectionTriggerTestId: 'type-section-trigger-cross_country_skiing',
      summaryTestId: 'cross-country-skiing-summary',
      fillTypeFields: async ({ page: detailPage }) => {
        await detailPage
          .getByTestId('snow-conditions-input')
          .fill('Fresh powder with groomed tracks');
      },
      assertSummary: async ({ summary }) => {
        await expect(summary).toContainText('Fresh powder with groomed tracks');
      },
    });
  });

  test('should pre-populate canyoning fields and abseiling pitches when a template is selected', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;

    // Create a template via API with specific canyoning data and pitches
    const templateName = `E2E Hydration Template ${Date.now()}`;
    const templateRes = await page.request.post('/api/templates', {
      data: {
        data: {
          type: 'activity-templates',
          attributes: {
            name: templateName,
            template_type: 'canyoning',
            region: 'Blue Mountains',
            french_grade: 'v4a3V*',
            pitches: [
              { pitch_number: 1, height: 15 },
              { pitch_number: 2, height: 25 },
            ],
          },
        },
      },
    });
    expect(templateRes.ok()).toBeTruthy();

    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Template Hydration ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Journal using template.');
    await page.getByLabel(/^canyoning$/i).check();

    await expect(page.getByTestId('canyoning-type-editor')).toBeVisible();

    // Select the template by typing to filter and trigger the dropdown
    await page.getByPlaceholder('Select a canyoning template...').click();
    await page
      .getByPlaceholder('Select a canyoning template...')
      .fill('E2E Hydration');

    // Wait for the option to appear and click it
    const option = page.getByRole('option', {
      name: new RegExp(templateName, 'i'),
    });
    await expect(option).toBeVisible();
    await option.click();

    // Verify Canyoning fields are populated
    await expect(page.getByTestId('french-grade-input')).toHaveValue('v4a3V*');

    // Verify Abseiling Trip editor is visible and pitches are populated
    await expect(page.getByTestId('abseiling-trip-type-editor')).toBeVisible();
    await expect(page.getByTestId('number-of-abseils-input')).toHaveValue('2');
    await expect(page.getByTestId('total-length-input')).toHaveValue('40');

    await expect(
      page.getByTestId('pitch-row-0').getByPlaceholder('Height')
    ).toHaveValue('15');
    await expect(
      page.getByTestId('pitch-row-1').getByPlaceholder('Height')
    ).toHaveValue('25');
  });

  test('should support inline template creation workflow', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page.getByLabel(/title/i).fill(`Template Creation ${Date.now()}`);
    await page.getByLabel(/content/i).fill('Testing inline template creation.');
    await page.getByLabel(/^canyoning$/i).check();

    await expect(page.getByTestId('canyoning-type-editor')).toBeVisible();

    // Open template selector by typing
    await page.getByPlaceholder('Select a canyoning template...').click();
    await page
      .getByPlaceholder('Select a canyoning template...')
      .fill('new template');

    // Click create new
    const createBtn = page.getByRole('option', {
      name: /\+ Create new template/i,
    });
    await expect(createBtn).toBeVisible();
    await createBtn.click();

    // Verify dialog opens
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // Fill new template
    const templateName = `UI Template ${Date.now()}`;
    await dialog.getByLabel('Template Name').fill(templateName);
    await dialog.getByLabel('Region').fill('Test Region');
    await dialog.getByRole('button', { name: 'Create Template' }).click();

    // Dialog should close
    await expect(dialog).toBeHidden();

    // Verify success toast
    await expect(page.getByText('Template created successfully')).toBeVisible();
  });

  test('should support saving abseiling pitches as a template', async ({
    authenticatedPage,
  }) => {
    const page = authenticatedPage;
    await navigateToNewJournal(page);

    await page
      .getByLabel(/title/i)
      .fill(`Abseil Pitches Template ${Date.now()}`);
    await page
      .getByLabel(/content/i)
      .fill('Testing saving pitches as a template.');
    await page.getByLabel(/^abseiling trip$/i).check();

    await expect(page.getByTestId('abseiling-trip-type-editor')).toBeVisible();

    // Add some pitches
    await page.getByTestId('add-pitch-button').click();
    await page.getByTestId('pitch-row-0').getByPlaceholder('Height').fill('45');
    await page.getByTestId('add-pitch-button').click();
    await page.getByTestId('pitch-row-1').getByPlaceholder('Height').fill('55');

    // Click "Save Pitches as Template"
    const saveAsTemplateBtn = page.getByTestId('save-as-template-button');
    await expect(saveAsTemplateBtn).toBeVisible();
    await saveAsTemplateBtn.click();

    // Verify dialog opens
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // Verify pitches are pre-populated inside the dialog's pitch editor
    await expect(dialog.getByTestId('pitch-row-0')).toBeVisible();
    await expect(
      dialog.getByTestId('pitch-row-0').getByPlaceholder('Height')
    ).toHaveValue('45');
    await expect(
      dialog.getByTestId('pitch-row-1').getByPlaceholder('Height')
    ).toHaveValue('55');

    // Fill new template
    const templateName = `Abseil UI Template ${Date.now()}`;
    await dialog.getByLabel('Template Name').fill(templateName);

    // Select the template type (since abseiling is not a template type, we must select one, e.g. canyoning)
    await dialog.getByRole('combobox', { name: 'Template Type' }).click();
    await page.getByRole('option', { name: 'Canyoning' }).click();

    await dialog.getByRole('button', { name: 'Create Template' }).click();

    // Dialog should close
    await expect(dialog).toBeHidden();

    // Verify success toast
    await expect(page.getByText('Template created successfully')).toBeVisible();
  });
});
