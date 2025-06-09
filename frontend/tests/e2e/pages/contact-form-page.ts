/**
 * Page object for contact creation and editing forms.
 */

import { Page, expect } from '@playwright/test';
import { BasePage } from './base-page';
import { TestContact } from '../fixtures/test-data';

export class ContactFormPage extends BasePage {
  constructor(page: Page) {
    super(page);
  }

  // Selectors
  private readonly selectors = {
    // Form container
    contactForm: '[data-testid="contact-form"]',
    formTitle: '[data-testid="form-title"]',
    
    // Form fields
    firstNameInput: '[data-testid="first-name-input"]',
    lastNameInput: '[data-testid="last-name-input"]',
    emailInput: '[data-testid="email-input"]',
    phoneInput: '[data-testid="phone-input"]',
    companyInput: '[data-testid="company-input"]',
    notesTextarea: '[data-testid="notes-textarea"]',
    
    // Tag management
    tagsSection: '[data-testid="tags-section"]',
    tagInput: '[data-testid="tag-input"]',
    addTagButton: '[data-testid="add-tag-button"]',
    tagItem: '[data-testid^="tag-item-"]',
    removeTagButton: '[data-testid^="remove-tag-"]',
    
    // Form actions
    saveButton: '[data-testid="save-contact-button"]',
    cancelButton: '[data-testid="cancel-button"]',
    deleteButton: '[data-testid="delete-contact-button"]',
    
    // Validation messages
    fieldError: '[data-testid^="field-error-"]',
    formError: '[data-testid="form-error"]',
    
    // Loading states
    formLoading: '[data-testid="form-loading"]',
    saveLoading: '[data-testid="save-loading"]'
  };

  /**
   * Navigate to create contact form
   */
  async navigateToCreateContact() {
    await this.goto('/contacts/new');
    await this.waitForLoad();
  }

  /**
   * Navigate to edit contact form
   */
  async navigateToEditContact(contactId: string) {
    await this.goto(`/contacts/${contactId}/edit`);
    await this.waitForLoad();
  }

  /**
   * Check if contact form is visible
   */
  async isContactFormVisible(): Promise<boolean> {
    return await this.isVisible(this.selectors.contactForm);
  }

  /**
   * Get form title
   */
  async getFormTitle(): Promise<string> {
    return await this.getTextContent(this.selectors.formTitle);
  }

  /**
   * Fill contact form with data
   */
  async fillContactForm(contact: Partial<TestContact>) {
    if (contact.firstName) {
      await this.fillInput(this.selectors.firstNameInput, contact.firstName);
    }
    
    if (contact.lastName) {
      await this.fillInput(this.selectors.lastNameInput, contact.lastName);
    }
    
    if (contact.email) {
      await this.fillInput(this.selectors.emailInput, contact.email);
    }
    
    if (contact.phone) {
      await this.fillInput(this.selectors.phoneInput, contact.phone);
    }
    
    if (contact.company) {
      await this.fillInput(this.selectors.companyInput, contact.company);
    }
    
    if (contact.notes) {
      await this.fillInput(this.selectors.notesTextarea, contact.notes);
    }
    
    // Add tags if provided
    if (contact.tags) {
      for (const tag of contact.tags) {
        await this.addTag(tag);
      }
    }
  }

  /**
   * Add a tag to the contact
   */
  async addTag(tag: string) {
    await this.fillInput(this.selectors.tagInput, tag);
    await this.clickElement(this.selectors.addTagButton);
  }

  /**
   * Remove a tag from the contact
   */
  async removeTag(tag: string) {
    await this.clickElement(`[data-testid="remove-tag-${tag}"]`);
  }

  /**
   * Get list of current tags
   */
  async getCurrentTags(): Promise<string[]> {
    const tagElements = await this.page.locator(this.selectors.tagItem).all();
    const tags: string[] = [];
    
    for (const element of tagElements) {
      const tagText = await element.textContent();
      if (tagText) {
        tags.push(tagText.trim());
      }
    }
    
    return tags;
  }

  /**
   * Save the contact form
   */
  async saveContact() {
    await this.clickElement(this.selectors.saveButton);
    
    // Wait for save operation to complete
    await this.waitForApiResponse('**/api/contacts**');
  }

  /**
   * Cancel form editing
   */
  async cancelForm() {
    await this.clickElement(this.selectors.cancelButton);
  }

  /**
   * Delete contact (only available in edit mode)
   */
  async deleteContact() {
    await this.clickElement(this.selectors.deleteButton);
    
    // Wait for delete operation to complete
    await this.waitForApiResponse('**/api/contacts/**', 10000);
  }

  /**
   * Check if form has validation errors
   */
  async hasValidationErrors(): Promise<boolean> {
    return await this.isVisible(this.selectors.fieldError) || 
           await this.isVisible(this.selectors.formError);
  }

  /**
   * Get validation error for specific field
   */
  async getFieldError(fieldName: string): Promise<string> {
    return await this.getTextContent(`[data-testid="field-error-${fieldName}"]`);
  }

  /**
   * Get general form error
   */
  async getFormError(): Promise<string> {
    return await this.getTextContent(this.selectors.formError);
  }

  /**
   * Check if form is in loading state
   */
  async isFormLoading(): Promise<boolean> {
    return await this.isVisible(this.selectors.formLoading);
  }

  /**
   * Check if save operation is in progress
   */
  async isSaveLoading(): Promise<boolean> {
    return await this.isVisible(this.selectors.saveLoading);
  }

  /**
   * Wait for form to finish loading
   */
  async waitForFormToLoad() {
    await this.page.waitForSelector(this.selectors.formLoading, { 
      state: 'hidden',
      timeout: 10000 
    });
  }

  /**
   * Verify form field values match contact data
   */
  async verifyFormValues(contact: Partial<TestContact>) {
    if (contact.firstName) {
      const firstName = await this.page.inputValue(this.selectors.firstNameInput);
      expect(firstName).toBe(contact.firstName);
    }
    
    if (contact.lastName) {
      const lastName = await this.page.inputValue(this.selectors.lastNameInput);
      expect(lastName).toBe(contact.lastName);
    }
    
    if (contact.email) {
      const email = await this.page.inputValue(this.selectors.emailInput);
      expect(email).toBe(contact.email);
    }
    
    if (contact.phone) {
      const phone = await this.page.inputValue(this.selectors.phoneInput);
      expect(phone).toBe(contact.phone);
    }
    
    if (contact.company) {
      const company = await this.page.inputValue(this.selectors.companyInput);
      expect(company).toBe(contact.company);
    }
    
    if (contact.notes) {
      const notes = await this.page.inputValue(this.selectors.notesTextarea);
      expect(notes).toBe(contact.notes);
    }
    
    if (contact.tags) {
      const currentTags = await this.getCurrentTags();
      for (const tag of contact.tags) {
        expect(currentTags).toContain(tag);
      }
    }
  }

  /**
   * Test form validation for required fields
   */
  async testRequiredFieldValidation() {
    // Try to save form without required fields
    await this.saveContact();
    
    // Should show validation errors
    expect(await this.hasValidationErrors()).toBe(true);
    
    // Check specific field errors
    const firstNameError = await this.getFieldError('firstName');
    expect(firstNameError).toContain('required');
    
    const lastNameError = await this.getFieldError('lastName');
    expect(lastNameError).toContain('required');
  }

  /**
   * Test email validation
   */
  async testEmailValidation() {
    // Fill invalid email
    await this.fillInput(this.selectors.emailInput, 'invalid-email');
    await this.saveContact();
    
    // Should show email validation error
    const emailError = await this.getFieldError('email');
    expect(emailError).toContain('valid email');
  }

  /**
   * Test phone validation
   */
  async testPhoneValidation() {
    // Fill invalid phone
    await this.fillInput(this.selectors.phoneInput, 'invalid-phone');
    await this.saveContact();
    
    // Should show phone validation error
    const phoneError = await this.getFieldError('phone');
    expect(phoneError).toContain('valid phone');
  }

  /**
   * Test responsive form layout
   */
  async testResponsiveForm() {
    // Test mobile layout
    await this.setViewportSize(BasePage.VIEWPORTS.MOBILE.width, BasePage.VIEWPORTS.MOBILE.height);
    await expect(this.page.locator(this.selectors.contactForm)).toBeVisible();
    
    // Form should be usable on mobile
    await this.fillInput(this.selectors.firstNameInput, 'Test');
    
    // Test tablet layout
    await this.setViewportSize(BasePage.VIEWPORTS.TABLET.width, BasePage.VIEWPORTS.TABLET.height);
    await expect(this.page.locator(this.selectors.contactForm)).toBeVisible();
    
    // Test desktop layout
    await this.setViewportSize(BasePage.VIEWPORTS.DESKTOP.width, BasePage.VIEWPORTS.DESKTOP.height);
    await expect(this.page.locator(this.selectors.contactForm)).toBeVisible();
  }

  /**
   * Verify form accessibility
   */
  async verifyFormAccessibility() {
    await this.checkAccessibility();
    
    // Check form has proper labels
    const inputs = [
      this.selectors.firstNameInput,
      this.selectors.lastNameInput,
      this.selectors.emailInput,
      this.selectors.phoneInput,
      this.selectors.companyInput
    ];
    
    for (const inputSelector of inputs) {
      const input = this.page.locator(inputSelector);
      const id = await input.getAttribute('id');
      if (id) {
        const label = await this.page.locator(`label[for="${id}"]`).count();
        expect(label).toBeGreaterThan(0);
      }
    }
    
    // Check form has proper ARIA attributes
    const form = this.page.locator(this.selectors.contactForm);
    await expect(form).toHaveAttribute('role', 'form');
  }
}
