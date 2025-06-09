/**
 * End-to-end tests for contact CRUD operations.
 *
 * Tests contact creation, editing, deletion, and form validation.
 * These tests define the expected behavior for ITER1-004 contact management forms.
 */

import { test, expect } from '@playwright/test';
import { LoginPage } from './pages/login-page';
import { ContactsPage } from './pages/contacts-page';
import { ContactFormPage } from './pages/contact-form-page';
import { setupApiMocks } from './utils/api-mocks';
import { testContacts, validationTestCases } from './fixtures/test-data';

test.describe('Contact CRUD Operations', () => {
  let loginPage: LoginPage;
  let contactsPage: ContactsPage;
  let contactFormPage: ContactFormPage;

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    contactsPage = new ContactsPage(page);
    contactFormPage = new ContactFormPage(page);

    // Set up API mocks for consistent testing
    await setupApiMocks(page);

    // Login before each test
    await loginPage.navigateToLogin();
    await loginPage.performOAuthLogin('github');
  });

  test('should create a new contact successfully', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Verify we're on the create contact form
    expect(await contactFormPage.isContactFormVisible()).toBe(true);
    expect(await contactFormPage.getFormTitle()).toContain('Create Contact');

    // Fill out the contact form
    const newContact = {
      firstName: 'Jane',
      lastName: 'Doe',
      email: 'jane.doe@example.com',
      phone: '+61 2 1234 5678',
      company: 'Example Corp',
      tags: ['work', 'client'],
      notes: 'New client contact',
    };

    await contactFormPage.fillContactForm(newContact);

    // Save the contact
    await contactFormPage.saveContact();

    // Should redirect to contacts list
    expect(await contactsPage.isContactsListVisible()).toBe(true);

    // Verify success message
    expect(await contactFormPage.hasSuccessMessage()).toBe(true);

    // Verify contact appears in list
    expect(await contactsPage.verifyContactInList(newContact)).toBe(true);
  });

  test('should edit an existing contact successfully', async () => {
    await contactsPage.navigateToContacts();

    // Click edit on first contact
    await contactsPage.clickEditContact(0);

    // Verify we're on the edit contact form
    expect(await contactFormPage.isContactFormVisible()).toBe(true);
    expect(await contactFormPage.getFormTitle()).toContain('Edit Contact');

    // Verify form is pre-filled with existing data
    await contactFormPage.verifyFormValues(testContacts[0]);

    // Update contact information
    const updatedContact = {
      ...testContacts[0],
      company: 'Updated Company',
      notes: 'Updated notes',
    };

    await contactFormPage.fillContactForm(updatedContact);

    // Save the changes
    await contactFormPage.saveContact();

    // Should redirect to contacts list
    expect(await contactsPage.isContactsListVisible()).toBe(true);

    // Verify success message
    expect(await contactFormPage.hasSuccessMessage()).toBe(true);
  });

  test('should delete a contact successfully', async () => {
    await contactsPage.navigateToContacts();

    // Get initial contact count
    const initialCount = await contactsPage.getContactCount();

    // Click edit on first contact
    await contactsPage.clickEditContact(0);

    // Delete the contact
    await contactFormPage.deleteContact();

    // Should redirect to contacts list
    expect(await contactsPage.isContactsListVisible()).toBe(true);

    // Verify success message
    expect(await contactFormPage.hasSuccessMessage()).toBe(true);

    // Verify contact count decreased
    const newCount = await contactsPage.getContactCount();
    expect(newCount).toBe(initialCount - 1);
  });

  test('should validate required fields', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Test required field validation
    await contactFormPage.testRequiredFieldValidation();
  });

  test('should validate email format', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Test email validation
    await contactFormPage.testEmailValidation();

    // Test valid email formats
    for (const validEmail of validationTestCases.email.valid) {
      await contactFormPage.fillInput(
        '[data-testid="email-input"]',
        validEmail
      );
      // Should not show validation error
      const emailError = await contactFormPage.getFieldError('email');
      expect(emailError).toBe('');
    }
  });

  test('should validate phone format', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Test phone validation
    await contactFormPage.testPhoneValidation();

    // Test valid phone formats
    for (const validPhone of validationTestCases.phone.valid) {
      await contactFormPage.fillInput(
        '[data-testid="phone-input"]',
        validPhone
      );
      // Should not show validation error
      const phoneError = await contactFormPage.getFieldError('phone');
      expect(phoneError).toBe('');
    }
  });

  test('should manage contact tags', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Add tags
    await contactFormPage.addTag('work');
    await contactFormPage.addTag('client');
    await contactFormPage.addTag('important');

    // Verify tags are added
    const tags = await contactFormPage.getCurrentTags();
    expect(tags).toContain('work');
    expect(tags).toContain('client');
    expect(tags).toContain('important');

    // Remove a tag
    await contactFormPage.removeTag('client');

    // Verify tag is removed
    const updatedTags = await contactFormPage.getCurrentTags();
    expect(updatedTags).not.toContain('client');
    expect(updatedTags).toContain('work');
    expect(updatedTags).toContain('important');
  });

  test('should handle form cancellation', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Fill some form data
    await contactFormPage.fillContactForm({
      firstName: 'Test',
      lastName: 'User',
    });

    // Cancel the form
    await contactFormPage.cancelForm();

    // Should return to contacts list
    expect(await contactsPage.isContactsListVisible()).toBe(true);

    // Contact should not be created
    expect(
      await contactsPage.verifyContactInList({
        firstName: 'Test',
        lastName: 'User',
      })
    ).toBe(false);
  });

  test('should handle API errors during creation', async () => {
    // Mock API error for contact creation
    await contactFormPage.page.route('**/api/contacts', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({
            errors: [
              {
                status: '400',
                title: 'Validation Error',
                detail: 'Email already exists',
              },
            ],
          }),
        });
      }
    });

    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Fill valid form data
    await contactFormPage.fillContactForm({
      firstName: 'John',
      lastName: 'Doe',
      email: 'existing@example.com',
    });

    // Try to save
    await contactFormPage.saveContact();

    // Should display error message
    expect(await contactFormPage.hasErrorMessage()).toBe(true);

    const errorMessage = await contactFormPage.getErrorMessage();
    expect(errorMessage).toContain('Email already exists');
  });

  test('should handle API errors during update', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickEditContact(0);

    // Mock API error for contact update
    await contactFormPage.page.route('**/api/contacts/*', async route => {
      if (route.request().method() === 'PUT') {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            errors: [
              {
                status: '500',
                title: 'Server Error',
                detail: 'Failed to update contact',
              },
            ],
          }),
        });
      }
    });

    // Update contact
    await contactFormPage.fillContactForm({
      company: 'Updated Company',
    });

    // Try to save
    await contactFormPage.saveContact();

    // Should display error message
    expect(await contactFormPage.hasErrorMessage()).toBe(true);

    const errorMessage = await contactFormPage.getErrorMessage();
    expect(errorMessage).toContain('Failed to update contact');
  });

  test('should work responsively on different screen sizes', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Test responsive form layout
    await contactFormPage.testResponsiveForm();

    // Test form submission on mobile
    await contactFormPage.setViewportSize(375, 667);
    await contactFormPage.fillContactForm({
      firstName: 'Mobile',
      lastName: 'User',
      email: 'mobile@example.com',
    });

    await contactFormPage.saveContact();

    // Should work the same on mobile
    expect(await contactsPage.isContactsListVisible()).toBe(true);
  });

  test('should support keyboard navigation', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Test tab navigation through form fields
    await contactFormPage.page.keyboard.press('Tab'); // First name
    await contactFormPage.page.keyboard.type('John');

    await contactFormPage.page.keyboard.press('Tab'); // Last name
    await contactFormPage.page.keyboard.type('Doe');

    await contactFormPage.page.keyboard.press('Tab'); // Email
    await contactFormPage.page.keyboard.type('john.doe@example.com');

    // Verify values were entered
    const firstName = await contactFormPage.page.inputValue(
      '[data-testid="first-name-input"]'
    );
    expect(firstName).toBe('John');
  });

  test('should verify form accessibility', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickAddContact();

    // Verify form accessibility
    await contactFormPage.verifyFormAccessibility();
  });

  test('should display Australian date formats in form', async () => {
    await contactsPage.navigateToContacts();
    await contactsPage.clickEditContact(0);

    // Verify created/updated dates are in Australian format
    const testDate = new Date('2024-01-15');
    await contactFormPage.verifyAustralianDateFormat(
      '[data-testid="contact-created-date"]',
      testDate
    );
  });
});
