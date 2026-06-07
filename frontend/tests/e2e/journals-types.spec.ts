/**
 * E2E Tests for Journal Types
 *
 * Tests creating journals with different types and verifying type-specific behavior.
 */

import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';

/**
 * Default date range for journal creation
 */
const DEFAULT_DATE_RANGE = {
  start: '2024-01-15T09:00:00Z',
  end: '2024-01-15T10:00:00Z',
} as const;

/**
 * Helper function to create a journal via API
 */
async function createJournal(
  page: Page,
  title: string,
  content: string,
  types: string[],
  dateRange?: { start: string; end: string }
) {
  const response = await page.request.post('/api/journals', {
    headers: {
      'Content-Type': 'application/vnd.api+json',
    },
    data: JSON.stringify({
      data: {
        type: 'journals',
        attributes: {
          title,
          content,
          event_date_range: dateRange ?? DEFAULT_DATE_RANGE,
          types,
        },
      },
    }),
  });

  expect(response.ok()).toBeTruthy();
  return response.json();
}

/**
 * Helper function to create a journal and register cleanup
 */
async function createJournalWithCleanup(
  page: Page,
  testCleanup: (cleanup: () => Promise<void>) => void,
  title: string,
  content: string,
  types: string[],
  dateRange?: { start: string; end: string }
) {
  const data = await createJournal(page, title, content, types, dateRange);
  const journalId = data.data.id;

  // Register cleanup
  testCleanup(async () => {
    await page.request.delete(`/api/journals/${journalId}`);
  });

  return data;
}

test.describe('Journal Types', () => {
  test.describe('Creating Journals with Types', () => {
    // Note: per-type creation through the UI is covered comprehensively in
    // journal-creation-ui.spec.ts. These remaining tests assert only the
    // raw API contract (types + auto-populated type_data) that the UI flow
    // cannot directly observe.

    test('should create journals with each supported type and populate type_data', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      // A single type per journal across the supported set, plus a multi-type
      // journal — each should round-trip its type and an empty type_data entry.
      const singleTypeCases = [
        'mood_rating',
        'plan',
        'travel',
        'outdoor_activity',
        'jogging',
        'bushwalking',
      ];

      for (const type of singleTypeCases) {
        const data = await createJournalWithCleanup(
          authenticatedPage,
          testCleanup,
          `${type} Test Journal`,
          `Testing ${type} type`,
          [type]
        );

        expect(data.data.attributes.types).toContain(type);
        expect(data.data.attributes.type_data).toHaveProperty(type);
      }

      // Multiple types on a single journal
      const multi = await createJournalWithCleanup(
        authenticatedPage,
        testCleanup,
        'Multi-Type Test Journal',
        'Testing multiple types',
        ['mood_rating', 'plan']
      );
      expect(multi.data.attributes.types).toContain('mood_rating');
      expect(multi.data.attributes.types).toContain('plan');
      expect(multi.data.attributes.type_data).toHaveProperty('mood_rating');
      expect(multi.data.attributes.type_data).toHaveProperty('plan');
    });

    test('should create a journal with outdoor_training type and custom focus areas', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      // Test creating an outdoor training journal with focus areas including "other"
      const response = await authenticatedPage.request.post('/api/journals', {
        headers: {
          'Content-Type': 'application/vnd.api+json',
        },
        data: JSON.stringify({
          data: {
            type: 'journals',
            attributes: {
              title: 'Training Journal',
              content: 'Practicing skills',
              event_date_range: DEFAULT_DATE_RANGE,
              types: ['outdoor_training'],
              type_data: {
                outdoor_training: {
                  focus_areas: ['canyoning', 'Wilderness First Aid'],
                },
              },
            },
          },
        }),
      });

      expect(response.ok()).toBeTruthy();
      const data = await response.json();
      const journalId = data.data.id;

      testCleanup(async () => {
        await authenticatedPage.request.delete(`/api/journals/${journalId}`);
      });

      expect(data.data.attributes.types).toContain('outdoor_training');
      expect(data.data.attributes.type_data).toHaveProperty('outdoor_training');
      expect(
        data.data.attributes.type_data.outdoor_training.focus_areas
      ).toContain('canyoning');
      expect(
        data.data.attributes.type_data.outdoor_training.focus_areas
      ).toContain('Wilderness First Aid');
    });
  });

  test.describe('Type Filtering', () => {
    test('should filter journals by type', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const page = authenticatedPage;
      const journalIds: string[] = [];

      // Create journals with different types
      const journalsData = [
        { title: 'Note Journal', types: ['note'] },
        { title: 'Mood Journal', types: ['mood_rating'] },
        { title: 'Plan Journal', types: ['plan'] },
      ];

      for (const journalData of journalsData) {
        const data = await createJournal(
          page,
          journalData.title,
          'Test content',
          journalData.types
        );
        journalIds.push(data.data.id);
      }

      // Register cleanup
      testCleanup(async () => {
        for (const id of journalIds) {
          await page.request.delete(`/api/journals/${id}`);
        }
      });

      // Test filtering by mood_rating type
      const filterResponse = await page.request.get(
        '/api/journals?type=mood_rating'
      );
      expect(filterResponse.ok()).toBeTruthy();
      const filterData = await filterResponse.json();

      // Verify all returned journals have mood_rating type
      for (const journal of filterData.data) {
        expect(journal.attributes.types).toContain('mood_rating');
      }

      // Verify the specific journal we created is in the list
      const ourJournal = filterData.data.find(
        (j: { id: string | number }) => String(j.id) === String(journalIds[1])
      );
      expect(ourJournal).toBeDefined();
      expect(ourJournal.attributes.title).toBe('Mood Journal');
    });
  });
});
