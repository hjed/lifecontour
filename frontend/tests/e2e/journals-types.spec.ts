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
    test('should create a journal with mood_rating type', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const data = await createJournalWithCleanup(
        authenticatedPage,
        testCleanup,
        'Mood Test Journal',
        'Testing mood rating type',
        ['mood_rating']
      );

      // Verify journal was created with correct type
      expect(data.data.attributes.types).toContain('mood_rating');
      expect(data.data.attributes.type_data).toHaveProperty('mood_rating');
    });

    test('should create a journal with plan type', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const data = await createJournalWithCleanup(
        authenticatedPage,
        testCleanup,
        'Plan Test Journal',
        'Testing plan type',
        ['plan']
      );

      // Verify journal was created with correct type
      expect(data.data.attributes.types).toContain('plan');
      expect(data.data.attributes.type_data).toHaveProperty('plan');
    });

    test('should create a journal with travel type', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const data = await createJournalWithCleanup(
        authenticatedPage,
        testCleanup,
        'Travel Test Journal',
        'Testing travel type',
        ['travel'],
        {
          start: '2024-01-15T09:00:00Z',
          end: '2024-01-20T10:00:00Z',
        }
      );

      // Verify journal was created with correct type
      expect(data.data.attributes.types).toContain('travel');
      expect(data.data.attributes.type_data).toHaveProperty('travel');
    });

    test('should create a journal with multiple types', async ({
      authenticatedPage,
      testCleanup,
    }) => {
      const data = await createJournalWithCleanup(
        authenticatedPage,
        testCleanup,
        'Multi-Type Test Journal',
        'Testing multiple types',
        ['mood_rating', 'plan'] // NOTE is only added when no other types are present
      );

      // Verify journal was created with all types
      expect(data.data.attributes.types).toContain('mood_rating');
      expect(data.data.attributes.types).toContain('plan');
      expect(data.data.attributes.type_data).toHaveProperty('mood_rating');
      expect(data.data.attributes.type_data).toHaveProperty('plan');
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

      // Verify we got exactly 1 mood_rating journal (the one we created)
      expect(filterData.data.length).toBe(1);

      // Verify the returned journal has mood_rating type
      expect(filterData.data[0].attributes.types).toContain('mood_rating');
      expect(filterData.data[0].attributes.title).toBe('Mood Journal');
    });
  });
});
