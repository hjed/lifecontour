/**
 * Page object for contacts list and management functionality.
 */

import { Page, expect, Locator } from '@playwright/test';
import { BasePage } from './base-page';
import { TestContact } from '../fixtures/test-data';

export class ContactsPage extends BasePage {
  constructor(page: Page) {
    super(page);
  }

  // Selectors
  private readonly selectors = {
    // Navigation
    contactsNavLink: '[data-testid="nav-contacts"]',
    
    // Contact list
    contactsList: '[data-testid="contacts-list"]',
    contactItem: '[data-testid^="contact-item-"]',
    contactName: '[data-testid="contact-name"]',
    contactEmail: '[data-testid="contact-email"]',
    contactCompany: '[data-testid="contact-company"]',
    contactTags: '[data-testid="contact-tags"]',
    
    // Empty state
    emptyState: '[data-testid="contacts-empty-state"]',
    emptyStateMessage: '[data-testid="empty-state-message"]',
    
    // Actions
    addContactButton: '[data-testid="add-contact-button"]',
    editContactButton: '[data-testid="edit-contact-button"]',
    deleteContactButton: '[data-testid="delete-contact-button"]',
    
    // Search
    searchInput: '[data-testid="contact-search-input"]',
    searchButton: '[data-testid="contact-search-button"]',
    searchResults: '[data-testid="search-results"]',
    searchResultItem: '[data-testid^="search-result-"]',
    searchHighlight: '[data-testid="search-highlight"]',
    clearSearchButton: '[data-testid="clear-search-button"]',
    
    // Filters
    filterButton: '[data-testid="filter-button"]',
    filterDropdown: '[data-testid="filter-dropdown"]',
    tagFilter: '[data-testid^="tag-filter-"]',
    
    // Pagination
    pagination: '[data-testid="pagination"]',
    paginationPrevious: '[data-testid="pagination-previous"]',
    paginationNext: '[data-testid="pagination-next"]',
    paginationPage: '[data-testid^="pagination-page-"]',
    
    // Loading states
    contactsLoading: '[data-testid="contacts-loading"]',
    searchLoading: '[data-testid="search-loading"]'
  };

  /**
   * Navigate to contacts page
   */
  async navigateToContacts() {
    await this.goto('/contacts');
    await this.waitForLoad();
  }

  /**
   * Click contacts navigation link
   */
  async clickContactsNavigation() {
    await this.clickElement(this.selectors.contactsNavLink);
    await this.waitForLoad();
  }

  /**
   * Check if contacts list is visible
   */
  async isContactsListVisible(): Promise<boolean> {
    return await this.isVisible(this.selectors.contactsList);
  }

  /**
   * Check if empty state is shown
   */
  async isEmptyStateVisible(): Promise<boolean> {
    return await this.isVisible(this.selectors.emptyState);
  }

  /**
   * Get empty state message
   */
  async getEmptyStateMessage(): Promise<string> {
    return await this.getTextContent(this.selectors.emptyStateMessage);
  }

  /**
   * Get number of contacts displayed
   */
  async getContactCount(): Promise<number> {
    return await this.page.locator(this.selectors.contactItem).count();
  }

  /**
   * Get contact details by index
   */
  async getContactDetails(index: number): Promise<Partial<TestContact>> {
    const contactElement = this.page.locator(this.selectors.contactItem).nth(index);
    
    const name = await contactElement.locator(this.selectors.contactName).textContent();
    const email = await contactElement.locator(this.selectors.contactEmail).textContent();
    const company = await contactElement.locator(this.selectors.contactCompany).textContent();
    
    // Parse name into first and last name
    const nameParts = name?.split(' ') || [];
    const firstName = nameParts[0] || '';
    const lastName = nameParts.slice(1).join(' ') || '';
    
    return {
      firstName,
      lastName,
      email: email || undefined,
      company: company || undefined
    };
  }

  /**
   * Click add contact button
   */
  async clickAddContact() {
    await this.clickElement(this.selectors.addContactButton);
  }

  /**
   * Click edit contact button for specific contact
   */
  async clickEditContact(index: number) {
    const contactElement = this.page.locator(this.selectors.contactItem).nth(index);
    await contactElement.locator(this.selectors.editContactButton).click();
  }

  /**
   * Click delete contact button for specific contact
   */
  async clickDeleteContact(index: number) {
    const contactElement = this.page.locator(this.selectors.contactItem).nth(index);
    await contactElement.locator(this.selectors.deleteContactButton).click();
  }

  /**
   * Search for contacts
   */
  async searchContacts(query: string) {
    await this.fillInput(this.selectors.searchInput, query);
    await this.clickElement(this.selectors.searchButton);
    
    // Wait for search results
    await this.waitForApiResponse('**/api/search/contacts**');
    await this.waitForLoadingToComplete();
  }

  /**
   * Clear search
   */
  async clearSearch() {
    await this.clickElement(this.selectors.clearSearchButton);
    await this.waitForLoadingToComplete();
  }

  /**
   * Get search results count
   */
  async getSearchResultsCount(): Promise<number> {
    return await this.page.locator(this.selectors.searchResultItem).count();
  }

  /**
   * Check if search highlighting is present
   */
  async hasSearchHighlighting(): Promise<boolean> {
    return await this.isVisible(this.selectors.searchHighlight);
  }

  /**
   * Open filter dropdown
   */
  async openFilters() {
    await this.clickElement(this.selectors.filterButton);
  }

  /**
   * Apply tag filter
   */
  async applyTagFilter(tag: string) {
    await this.openFilters();
    await this.clickElement(`[data-testid="tag-filter-${tag}"]`);
  }

  /**
   * Check if pagination is visible
   */
  async isPaginationVisible(): Promise<boolean> {
    return await this.isVisible(this.selectors.pagination);
  }

  /**
   * Go to next page
   */
  async goToNextPage() {
    await this.clickElement(this.selectors.paginationNext);
    await this.waitForLoadingToComplete();
  }

  /**
   * Go to previous page
   */
  async goToPreviousPage() {
    await this.clickElement(this.selectors.paginationPrevious);
    await this.waitForLoadingToComplete();
  }

  /**
   * Go to specific page
   */
  async goToPage(pageNumber: number) {
    await this.clickElement(`[data-testid="pagination-page-${pageNumber}"]`);
    await this.waitForLoadingToComplete();
  }

  /**
   * Check if contacts are loading
   */
  async isContactsLoading(): Promise<boolean> {
    return await this.isVisible(this.selectors.contactsLoading);
  }

  /**
   * Wait for contacts to load
   */
  async waitForContactsToLoad() {
    await this.page.waitForSelector(this.selectors.contactsLoading, { 
      state: 'hidden',
      timeout: 10000 
    });
  }

  /**
   * Verify contact appears in list
   */
  async verifyContactInList(contact: Partial<TestContact>): Promise<boolean> {
    const contactCount = await this.getContactCount();
    
    for (let i = 0; i < contactCount; i++) {
      const contactDetails = await this.getContactDetails(i);
      
      if (contactDetails.firstName === contact.firstName && 
          contactDetails.lastName === contact.lastName) {
        return true;
      }
    }
    
    return false;
  }

  /**
   * Test responsive contacts list
   */
  async testResponsiveContactsList() {
    // Test mobile layout
    await this.setViewportSize(BasePage.VIEWPORTS.MOBILE.width, BasePage.VIEWPORTS.MOBILE.height);
    await expect(this.page.locator(this.selectors.contactsList)).toBeVisible();
    
    // Check if mobile menu is available
    if (await this.hasMobileMenu()) {
      await this.openMobileMenu();
      await expect(this.page.locator(this.selectors.contactsNavLink)).toBeVisible();
    }
    
    // Test tablet layout
    await this.setViewportSize(BasePage.VIEWPORTS.TABLET.width, BasePage.VIEWPORTS.TABLET.height);
    await expect(this.page.locator(this.selectors.contactsList)).toBeVisible();
    
    // Test desktop layout
    await this.setViewportSize(BasePage.VIEWPORTS.DESKTOP.width, BasePage.VIEWPORTS.DESKTOP.height);
    await expect(this.page.locator(this.selectors.contactsList)).toBeVisible();
  }

  /**
   * Verify contacts page accessibility
   */
  async verifyContactsPageAccessibility() {
    await this.checkAccessibility();
    
    // Check search input has proper label
    const searchInput = this.page.locator(this.selectors.searchInput);
    await expect(searchInput).toHaveAttribute('aria-label');
    
    // Check contact items have proper roles
    const contactItems = await this.page.locator(this.selectors.contactItem).all();
    for (const item of contactItems) {
      const role = await item.getAttribute('role');
      expect(role).toBeTruthy();
    }
  }
}
