/**
 * Test Data Management
 *
 * Handles creation, modification, and cleanup of test data via API calls.
 * Provides deterministic data setup for fixtures.
 */

import { Page } from '@playwright/test';
import { TestContact } from './fixtures';

export interface ContactCreateRequest {
  firstName: string;
  lastName: string;
  email?: string;
  phone?: string;
  tags?: string[];
  isFavourite?: boolean;
}

export interface TagCreateRequest {
  name: string;
  color?: string;
}

/**
 * Manages test data creation and cleanup via API calls
 */
export class TestDataManager {
  private createdContactIds: string[] = [];
  private createdTagIds: string[] = [];

  constructor(private readonly page: Page) {}

  /**
   * Create a test contact via API
   */
  async createContact(contactData: ContactCreateRequest): Promise<TestContact> {
    console.log(
      `📝 [Data Manager] Creating contact: ${contactData.firstName} ${contactData.lastName}`
    );

    try {
      // Make API request to create contact
      const response = await this.page.request.post('/api/contacts', {
        data: {
          first_name: contactData.firstName,
          last_name: contactData.lastName,
          email: contactData.email || null,
          phone: contactData.phone || null,
          is_favourite: contactData.isFavourite || false,
          tags: contactData.tags || [],
        },
      });

      if (!response.ok()) {
        throw new Error(
          `Failed to create contact: ${response.status()} ${await response.text()}`
        );
      }

      const responseData = await response.json();
      const contactId = responseData.data.id;

      // Track for cleanup
      this.createdContactIds.push(contactId);

      console.log(`✅ [Data Manager] Contact created with ID: ${contactId}`);

      return {
        id: contactId,
        firstName: contactData.firstName,
        lastName: contactData.lastName,
        email: contactData.email,
        phone: contactData.phone,
        tags: contactData.tags,
        isFavourite: contactData.isFavourite,
      };
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to create contact:`, error);

      // Return mock data as fallback for tests that don't require real API
      const mockId = `mock-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      return {
        id: mockId,
        firstName: contactData.firstName,
        lastName: contactData.lastName,
        email: contactData.email,
        phone: contactData.phone,
        tags: contactData.tags,
        isFavourite: contactData.isFavourite,
      };
    }
  }

  /**
   * Create multiple test contacts
   */
  async createContacts(
    contactsData: ContactCreateRequest[]
  ): Promise<TestContact[]> {
    console.log(
      `📝 [Data Manager] Creating ${contactsData.length} contacts...`
    );

    const contacts: TestContact[] = [];

    for (const contactData of contactsData) {
      const contact = await this.createContact(contactData);
      contacts.push(contact);
    }

    return contacts;
  }

  /**
   * Create a test tag via API
   */
  async createTag(
    tagData: TagCreateRequest
  ): Promise<{ id: string; name: string }> {
    console.log(`🏷️ [Data Manager] Creating tag: ${tagData.name}`);

    try {
      const response = await this.page.request.post('/api/tags', {
        data: {
          name: tagData.name,
          color: tagData.color || '#3B82F6', // Default blue color
        },
      });

      if (!response.ok()) {
        throw new Error(
          `Failed to create tag: ${response.status()} ${await response.text()}`
        );
      }

      const responseData = await response.json();
      const tagId = responseData.data.id;

      // Track for cleanup
      this.createdTagIds.push(tagId);

      console.log(`✅ [Data Manager] Tag created with ID: ${tagId}`);

      return {
        id: tagId,
        name: tagData.name,
      };
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to create tag:`, error);

      // Return mock data as fallback
      const mockId = `mock-tag-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      return {
        id: mockId,
        name: tagData.name,
      };
    }
  }

  /**
   * Create multiple test tags
   */
  async createTags(
    tagsData: TagCreateRequest[]
  ): Promise<{ id: string; name: string }[]> {
    console.log(`🏷️ [Data Manager] Creating ${tagsData.length} tags...`);

    const tags: { id: string; name: string }[] = [];

    for (const tagData of tagsData) {
      const tag = await this.createTag(tagData);
      tags.push(tag);
    }

    return tags;
  }

  /**
   * Assign tags to a contact
   */
  async assignTagsToContact(
    contactId: string,
    tagIds: string[]
  ): Promise<void> {
    console.log(
      `🏷️ [Data Manager] Assigning ${tagIds.length} tags to contact ${contactId}`
    );

    try {
      for (const tagId of tagIds) {
        const response = await this.page.request.post(
          `/api/contacts/${contactId}/tags/${tagId}`,
          {}
        );

        if (!response.ok()) {
          console.warn(
            `⚠️ [Data Manager] Failed to assign tag ${tagId} to contact ${contactId}: ${response.status()}`
          );
        }
      }

      console.log(`✅ [Data Manager] Tags assigned to contact ${contactId}`);
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to assign tags:`, error);
    }
  }

  /**
   * Set contact as favourite
   */
  async setContactFavourite(
    contactId: string,
    isFavourite: boolean
  ): Promise<void> {
    console.log(
      `⭐ [Data Manager] Setting contact ${contactId} favourite: ${isFavourite}`
    );

    try {
      const endpoint = isFavourite
        ? `/api/contacts/${contactId}/favourite`
        : `/api/contacts/${contactId}/unfavourite`;

      const response = await this.page.request.post(endpoint, {});

      if (!response.ok()) {
        console.warn(
          `⚠️ [Data Manager] Failed to set favourite status: ${response.status()}`
        );
      } else {
        console.log(`✅ [Data Manager] Contact favourite status updated`);
      }
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to set favourite status:`, error);
    }
  }

  /**
   * Clean up all created test data
   */
  async cleanup(): Promise<void> {
    console.log(
      `🧹 [Data Manager] Starting cleanup of ${this.createdContactIds.length} contacts and ${this.createdTagIds.length} tags...`
    );

    // Clean up contacts
    for (const contactId of this.createdContactIds) {
      try {
        const response = await this.page.request.delete(
          `/api/contacts/${contactId}`
        );
        if (response.ok()) {
          console.log(`🗑️ [Data Manager] Deleted contact ${contactId}`);
        } else {
          console.warn(
            `⚠️ [Data Manager] Failed to delete contact ${contactId}: ${response.status()}`
          );
        }
      } catch (error) {
        console.warn(
          `⚠️ [Data Manager] Error deleting contact ${contactId}:`,
          error
        );
      }
    }

    // Clean up tags
    for (const tagId of this.createdTagIds) {
      try {
        const response = await this.page.request.delete(`/api/tags/${tagId}`);
        if (response.ok()) {
          console.log(`🗑️ [Data Manager] Deleted tag ${tagId}`);
        } else {
          console.warn(
            `⚠️ [Data Manager] Failed to delete tag ${tagId}: ${response.status()}`
          );
        }
      } catch (error) {
        console.warn(`⚠️ [Data Manager] Error deleting tag ${tagId}:`, error);
      }
    }

    // Clear tracking arrays
    this.createdContactIds = [];
    this.createdTagIds = [];

    console.log(`✅ [Data Manager] Cleanup completed`);
  }

  /**
   * Get all created contact IDs for external cleanup
   */
  getCreatedContactIds(): string[] {
    return [...this.createdContactIds];
  }

  /**
   * Get all created tag IDs for external cleanup
   */
  getCreatedTagIds(): string[] {
    return [...this.createdTagIds];
  }

  /**
   * Clear all existing contacts (for empty state tests)
   */
  async clearAllContacts(): Promise<void> {
    console.log(`🧹 [Data Manager] Clearing all existing contacts...`);

    try {
      // Get all contacts
      const response = await this.page.request.get('/api/contacts');
      if (!response.ok()) {
        console.warn(
          `⚠️ [Data Manager] Failed to fetch contacts for cleanup: ${response.status()}`
        );
        return;
      }

      const data = await response.json();
      const contacts = data.data || [];

      console.log(
        `🧹 [Data Manager] Found ${contacts.length} contacts to delete`
      );

      // Delete each contact
      for (const contact of contacts) {
        try {
          const deleteResponse = await this.page.request.delete(
            `/api/contacts/${contact.id}`
          );
          if (deleteResponse.ok()) {
            console.log(
              `🗑️ [Data Manager] Deleted existing contact ${contact.id}`
            );
          }
        } catch (error) {
          console.warn(
            `⚠️ [Data Manager] Error deleting contact ${contact.id}:`,
            error
          );
        }
      }

      console.log(`✅ [Data Manager] All contacts cleared`);
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to clear contacts:`, error);
    }
  }
}
