import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Contact Tag Editing', () => {
  test('should add an existing tag to a contact via tags editor', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Create a contact and a tag
    const contacts = await dataManager.createContacts([
      { firstName: 'TagTest', lastName: 'Add' },
    ]);
    const tags = await dataManager.createTags([
      { name: `AddTag-${Date.now()}`, color: '#3182CE' },
    ]);

    testCleanup(async () => await dataManager.cleanup());

    const contact = contacts[0];
    const tag = tags[0];

    // Navigate to the contact detail page
    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Wait for the tags editor to be visible (use first() for desktop/mobile duplicate)
    const tagsEditor = authenticatedPage
      .locator('[data-testid="contact-tags-editor"]')
      .first();
    await expect(tagsEditor).toBeVisible();

    // Click "Add Tag" button (scoped to the visible editor)
    await tagsEditor.locator('[data-testid="add-tag-button"]').click();

    // Click the tag option
    await authenticatedPage
      .locator(`[data-testid="tag-option-${tag.id}"]`)
      .click();

    // Verify the tag badge appears on the contact (scoped to visible editor)
    await expect(
      tagsEditor.locator(`[data-testid="tag-badge-${tag.id}"]`)
    ).toBeVisible();
    await expect(
      tagsEditor.locator(`[data-testid="tag-badge-${tag.id}"]`)
    ).toContainText(tag.name);
  });

  test('should remove a tag from a contact via tags editor', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    // Create tag, contact, and assign the tag
    const tags = await dataManager.createTags([
      { name: `RemoveTag-${Date.now()}`, color: '#E53E3E' },
    ]);
    const contacts = await dataManager.createContacts([
      { firstName: 'TagTest', lastName: 'Remove' },
    ]);
    await dataManager.assignTagsToContact(contacts[0].id, [tags[0].id]);

    testCleanup(async () => await dataManager.cleanup());

    const contact = contacts[0];
    const tag = tags[0];

    // Navigate to the contact detail page
    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Scope to the first visible editor
    const tagsEditor = authenticatedPage
      .locator('[data-testid="contact-tags-editor"]')
      .first();

    // Verify the tag is displayed
    await expect(
      tagsEditor.locator(`[data-testid="tag-badge-${tag.id}"]`)
    ).toBeVisible();

    // Click the remove button (scoped to first editor)
    await tagsEditor.locator(`[data-testid="remove-tag-${tag.id}"]`).click();

    // Verify the tag badge is removed from the first editor
    await expect(
      tagsEditor.locator(`[data-testid="tag-badge-${tag.id}"]`)
    ).not.toBeVisible();
  });

  test('should create a new tag and assign it to a contact', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const dataManager = new TestDataManager(authenticatedPage);

    const contacts = await dataManager.createContacts([
      { firstName: 'TagTest', lastName: 'Create' },
    ]);

    testCleanup(async () => await dataManager.cleanup());

    const contact = contacts[0];
    const newTagName = `NewTag-${Date.now()}`;

    // Navigate to the contact detail page
    await authenticatedPage.goto(`/contacts/${contact.id}`);

    // Scope to the first visible editor
    const tagsEditor = authenticatedPage
      .locator('[data-testid="contact-tags-editor"]')
      .first();
    await expect(tagsEditor).toBeVisible();

    // Click "Add Tag" button
    await tagsEditor.locator('[data-testid="add-tag-button"]').click();

    // Type a tag name that doesn't exist
    await authenticatedPage
      .locator('[data-testid="tag-search-input"]')
      .fill(newTagName);

    // Click the "Create" option
    await authenticatedPage
      .locator('[data-testid="create-tag-option"]')
      .click();

    // We should now see the create form; click "Create & Add"
    await expect(
      authenticatedPage.locator('[data-testid="confirm-create-tag"]')
    ).toBeVisible();
    await authenticatedPage
      .locator('[data-testid="confirm-create-tag"]')
      .click();

    // Verify the new tag badge appears on the contact
    await expect(tagsEditor).toContainText(newTagName);
  });

  test('should not regress existing inline editing alongside tag editing', async ({
    contactsWithData,
  }) => {
    const { page, contacts } = contactsWithData;
    const contact = contacts[0];

    // Navigate to the contact detail page
    await page.goto(`/contacts/${contact.id}`);

    // Verify tags editor is present (use first() for desktop/mobile duplicate)
    await expect(
      page.locator('[data-testid="contact-tags-editor"]').first()
    ).toBeVisible();

    // Verify inline editing still works
    const firstNameField = page.locator('[data-testid="first-name-field"]');
    await firstNameField.click();
    const input = page.locator('[data-testid="first-name-field"] input');
    await expect(input).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(input).not.toBeVisible();
  });
});
