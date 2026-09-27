import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Gear used on a journal', () => {
  test('lists every gear item a journal records', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);
    testCleanup(async () => {
      await dataManager.cleanup();
    });

    const rope = await dataManager.createGearItem('Static rope 60m');
    const harness = await dataManager.createGearItem('Harness');
    const journal = await dataManager.createGearUsageJournal({
      title: 'Canyon trip with its gear',
      gearItemIds: [rope.id, harness.id],
      start: '2025-03-08T09:00:00.000Z',
      end: '2025-03-08T17:00:00.000Z',
    });

    await page.goto(`/journals/${journal.id}`);
    await page.getByRole('button', { name: 'Expand Gear Usage' }).click();

    const gear = page.getByTestId('gear-usage-summary');
    await expect(gear.getByTestId('gear-usage-item')).toHaveText([
      rope.name,
      harness.name,
    ]);
  });
});
