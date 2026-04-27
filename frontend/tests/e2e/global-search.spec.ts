/**
 * E2E Tests for Global Search
 *
 * Tests that the global header search box fetches live suggestions
 * and supports proper combobox navigation.
 */

import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';
import { waitForContactSearchIndexing } from './utils/test-helpers';

test.describe('Global Header Search', () => {
  test('should display search suggestions from backend and navigate to contact', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a contact
    const contact = await dataManager.createContact({
      firstName: 'GlobalSearchTest',
      lastName: 'Contact',
    });

    testCleanup(async () => await dataManager.cleanup());

    // Wait for the contact to be indexed in MeiliSearch
    const contactName = `${contact.firstName} ${contact.lastName}`;
    await waitForContactSearchIndexing(page, contact.firstName, contactName);

    // Go to the dashboard
    await page.goto('/');

    // Locate the global search input in the header
    const searchInput = page.getByRole('combobox', { name: /global search/i });
    await expect(searchInput).toBeVisible();

    // Type the contact name
    await searchInput.fill(contact.firstName);

    // Wait for the listbox and options to appear
    const listbox = page.getByRole('listbox', { name: /search suggestions/i });
    await expect(listbox).toBeVisible({ timeout: 10000 });

    // Debug: print all options
    const options = await page.getByRole('option').allTextContents();
    console.debug('Available options:', options);

    const option = page.getByRole('option', { name: contactName });
    await expect(option).toBeVisible({ timeout: 10000 });
    await expect(option).toBeVisible();

    // Click the suggestion
    await option.click();

    // Verify it navigates to the contact detail page
    await expect(page).toHaveURL(new RegExp(`/contacts/${contact.id}`));
  });

  test('should navigate to dedicated search results page on Enter', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a contact
    const contact = await dataManager.createContact({
      firstName: 'SearchResults',
      lastName: 'Target',
    });

    testCleanup(async () => await dataManager.cleanup());

    // Wait for the contact to be indexed in MeiliSearch
    const contactName = `${contact.firstName} ${contact.lastName}`;
    await waitForContactSearchIndexing(page, contact.firstName, contactName);

    // Go to the dashboard
    await page.goto('/');

    // Locate the global search input in the header
    const searchInput = page.getByRole('combobox', { name: /global search/i });
    await expect(searchInput).toBeVisible();

    // Type the query
    await searchInput.fill('SearchResults');

    // Wait for the listbox and options to appear
    const listbox = page.getByRole('listbox', { name: /search suggestions/i });
    await expect(listbox).toBeVisible({ timeout: 10000 });

    // Press Enter to trigger search
    await searchInput.press('Enter');

    // Verify it navigates to the search results page
    await expect(page).toHaveURL(/\/search\?q=SearchResults/);

    // Verify the results page renders the contact correctly
    const resultsHeading = page.getByRole('heading', {
      name: /Search Results/i,
    });
    await expect(resultsHeading).toBeVisible({ timeout: 10000 });

    const contactsHeading = page.getByRole('heading', {
      name: /Contacts \(\d+\)/i,
    });
    await expect(contactsHeading).toBeVisible();

    const contactCard = page.getByRole('link', {
      name: new RegExp(contactName, 'i'),
    });
    await expect(contactCard).toBeVisible();
  });

  test('should display favourite badge for favourite contacts on results page', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Create a favourite contact
    const contact = await dataManager.createContact({
      firstName: 'FavBadge',
      lastName: 'Tester',
      isFavourite: true,
    });

    testCleanup(async () => await dataManager.cleanup());

    // Wait for the contact to be indexed in MeiliSearch
    const contactName = `${contact.firstName} ${contact.lastName}`;
    await waitForContactSearchIndexing(page, contact.firstName, contactName);

    // Go to the dashboard
    await page.goto('/');

    // Locate the global search input
    const searchInput = page.getByRole('combobox', { name: /global search/i });
    await expect(searchInput).toBeVisible();

    // Type the query
    await searchInput.fill(contact.firstName);

    // Wait for the listbox
    const listbox = page.getByRole('listbox', { name: /search suggestions/i });
    await expect(listbox).toBeVisible({ timeout: 10000 });

    // Press Enter to navigate to the search results page
    await searchInput.press('Enter');

    // Wait for the search results page
    await expect(page).toHaveURL(
      new RegExp(`/search\\?q=${contact.firstName}`)
    );

    const resultsHeading = page.getByRole('heading', {
      name: /Search Results/i,
    });
    await expect(resultsHeading).toBeVisible({ timeout: 10000 });

    // Verify the contact card has the favourite badge
    const contactCard = page.getByTestId(`search-contact-${contact.id}`);
    await expect(contactCard).toBeVisible();

    const favouriteBadge = contactCard.getByLabel('Favourite contact');
    await expect(favouriteBadge).toBeVisible();

    // Verify the link goes to the contact detail page
    const contactLink = contactCard.getByRole('link', {
      name: new RegExp(contactName, 'i'),
    });
    await expect(contactLink).toHaveAttribute(
      'href',
      `/contacts/${contact.id}`
    );
  });

  test('should rank favourite contacts higher than non-favourites', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // Use a shared unique prefix so both contacts match the same query
    const uniquePrefix = `RankOrder_${crypto.randomUUID().slice(0, 6)}`;

    // Create a non-favourite contact first
    const nonFav = await dataManager.createContact({
      firstName: uniquePrefix,
      lastName: 'Beta',
      isFavourite: false,
    });

    // Create a favourite contact
    const fav = await dataManager.createContact({
      firstName: uniquePrefix,
      lastName: 'Alpha',
      isFavourite: true,
    });

    testCleanup(async () => await dataManager.cleanup());

    // Wait for both to be indexed
    const nonFavName = `${nonFav.firstName} ${nonFav.lastName}`;
    const favName = `${fav.firstName} ${fav.lastName}`;

    await waitForContactSearchIndexing(page, uniquePrefix, nonFavName);
    await waitForContactSearchIndexing(page, uniquePrefix, favName);

    // Go to the dashboard
    await page.goto('/');

    // Search for the shared prefix
    const searchInput = page.getByRole('combobox', { name: /global search/i });
    await expect(searchInput).toBeVisible();
    await searchInput.fill(uniquePrefix);

    // Wait for the listbox
    const listbox = page.getByRole('listbox', { name: /search suggestions/i });
    await expect(listbox).toBeVisible({ timeout: 10000 });

    // Press Enter to navigate to results page
    await searchInput.press('Enter');

    // Wait for the search results page
    await expect(page).toHaveURL(new RegExp(`/search\\?q=${uniquePrefix}`));

    const resultsHeading = page.getByRole('heading', {
      name: /Search Results/i,
    });
    await expect(resultsHeading).toBeVisible({ timeout: 10000 });

    // Verify both contacts appear
    const favCard = page.getByTestId(`search-contact-${fav.id}`);
    const nonFavCard = page.getByTestId(`search-contact-${nonFav.id}`);
    await expect(favCard).toBeVisible();
    await expect(nonFavCard).toBeVisible();

    // Verify the favourite appears first by comparing DOM order
    const contactCards = page.locator('[data-testid^="search-contact-"]');
    const firstCardTestId = await contactCards
      .first()
      .getAttribute('data-testid');
    expect(firstCardTestId).toBe(`search-contact-${fav.id}`);
  });
});
