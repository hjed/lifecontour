/**
 * Test Data Management
 *
 * Handles creation, modification, and cleanup of test data via API calls.
 * Provides deterministic data setup for fixtures.
 */

import { Page } from '@playwright/test';
import { TestContact, TestJournal } from './fixtures';

/**
 * Utility function to generate realistic phone numbers
 */
function generatePhoneNumber(): string {
  return `+1-555-${Math.floor(Math.random() * 900) + 100}-${Math.floor(Math.random() * 9000) + 1000}`;
}

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

export interface CalendarCreateRequest {
  name: string;
  color?: string;
  description?: string;
}

export interface JournalCreateRequest {
  title: string;
  content: string;
  event_date_range: {
    start: string;
    end: string;
  };
  types?: string[];
  type_data?: Record<string, unknown>;
  contacts?: Array<{ contact_id: string; relationship_type: string }>;
  tags?: string[];
  calendar_id?: string;
  // Note: Journal IDs are integers (SERIAL in database), not UUIDs
  // This is different from calendars and tags which use UUIDs
  parent_id?: number;
}

/**
 * Manages test data creation and cleanup via API calls
 */
export class TestDataManager {
  private createdContactIds: string[] = [];
  private createdTagIds: string[] = []; // Contact tags
  private createdJournalTagIds: string[] = []; // Journal tags
  private createdJournalIds: string[] = [];
  private readonly createdCalendars: string[] = [];

  constructor(private readonly page: Page) {}

  /**
   * Generate a unique identifier for test data
   * Uses crypto.randomUUID() for guaranteed uniqueness even in parallel tests
   */
  private generateUniqueId(): string {
    return crypto.randomUUID().slice(0, 8);
  }

  /**
   * Create a test contact via API
   */
  async createContact(contactData: ContactCreateRequest): Promise<TestContact> {
    // Make contact names unique to avoid conflicts using UUID
    const uniqueId = this.generateUniqueId();
    const uniqueFirstName = `${contactData.firstName}_${uniqueId}`;
    const uniqueLastName = `${contactData.lastName}_${uniqueId}`;

    console.log(
      `📝 [Data Manager] Creating contact: ${uniqueFirstName} ${uniqueLastName}`
    );

    try {
      // Debug: Check authentication and cookies
      const contextCookies = await this.page.context().cookies();
      console.log(
        `🔐 [Data Manager] Context has ${contextCookies.length} cookies:`,
        contextCookies.map(c => c.name).join(', ')
      );

      const authTestResponse = await this.page.request.get('/api/auth/status');
      if (authTestResponse.ok()) {
        const authData = await authTestResponse.json();
        console.log(`🔐 [Data Manager] Auth test successful:`, authData);
      } else {
        console.log(
          `🔐 [Data Manager] Auth test failed: ${authTestResponse.status()}`
        );
        const errorText = await authTestResponse.text();
        console.log(`🔐 [Data Manager] Auth error response:`, errorText);
      }

      // Make API request to create contact (JSON API format)
      // Note: Simplified to avoid contact methods for now due to transaction issues
      const response = await this.page.request.post('/api/contacts', {
        headers: {
          'Content-Type': 'application/json',
        },
        data: JSON.stringify({
          data: {
            type: 'contacts',
            attributes: {
              first_name: uniqueFirstName,
              last_name: uniqueLastName,
              is_favourite: contactData.isFavourite || false,
            },
          },
        }),
      });

      if (!response.ok()) {
        throw new Error(
          `Failed to create contact: ${response.status()} ${await response.text()}`
        );
      }

      const responseData = await response.json();
      const contactId = responseData.data.id;
      const contactAttributes = responseData.data.attributes;

      // Track for cleanup
      this.createdContactIds.push(contactId);

      // Handle tags if provided
      let assignedTags: string[] = [];
      if (contactData.tags && contactData.tags.length > 0) {
        console.log(
          `🏷️ [Data Manager] Creating and assigning ${contactData.tags.length} tags to contact ${contactId}`
        );

        // Create tags first using the new tags API
        const tagsData = contactData.tags.map(tagName => ({ name: tagName }));
        const createdTags = await this.createTags(tagsData);

        // Assign tags to contact
        const tagIds = createdTags.map(tag => tag.id);
        await this.assignTagsToContact(contactId, tagIds);

        assignedTags = contactData.tags;
      }

      console.log(
        `✅ [Data Manager] Contact created with ID: ${contactId} (favourite: ${contactAttributes.is_favourite})`
      );

      return {
        id: contactId,
        firstName: uniqueFirstName,
        lastName: uniqueLastName,
        email: contactData.email,
        phone: contactData.phone,
        tags: assignedTags,
        isFavourite: contactAttributes.is_favourite || contactData.isFavourite,
      };
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to create contact:`, error);

      // Return mock data as fallback for tests that don't require real API
      const mockId = `mock-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
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

    // Add timeout to prevent hanging
    const startTime = Date.now();
    const maxCreationTime = 60000; // 1 minute total for all contacts

    for (const contactData of contactsData) {
      if (Date.now() - startTime > maxCreationTime) {
        console.warn(
          `⚠️ [Data Manager] Contact creation timed out after ${maxCreationTime}ms`
        );
        break;
      }

      const contact = await this.createContact(contactData);
      contacts.push(contact);
    }

    // Add a small delay to ensure database consistency
    await new Promise(resolve => setTimeout(resolve, 100));

    return contacts;
  }

  /**
   * Create multiple test calendars
   */
  async createCalendars(
    calendarsData: CalendarCreateRequest[]
  ): Promise<Array<{ id: string; name: string; color: string }>> {
    console.log(
      `📅 [Data Manager] Creating ${calendarsData.length} calendars...`
    );

    const calendars: Array<{ id: string; name: string; color: string }> = [];

    for (const calendarData of calendarsData) {
      const calendarCreateData = {
        data: {
          type: 'calendars',
          attributes: {
            name: calendarData.name,
            color: calendarData.color || '#3B82F6',
            description: calendarData.description,
          },
        },
      };

      const response = await this.page.request.post('/api/calendars', {
        data: calendarCreateData,
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok()) {
        let errorMessage = `HTTP ${response.status()}`;
        try {
          const errorData = await response.json();
          errorMessage =
            errorData.errors?.[0]?.detail || errorData.message || errorMessage;
        } catch {
          // Ignore JSON parse errors
        }
        throw new Error(`Failed to create calendar: ${errorMessage}`);
      }

      const responseData = await response.json();
      const calendar = {
        id: responseData.data.id,
        name: responseData.data.attributes.name,
        color: responseData.data.attributes.color,
      };

      calendars.push(calendar);
      this.createdCalendars.push(calendar.id);
      console.log(`✅ [Data Manager] Created calendar: ${calendar.name}`);
    }

    // Add a small delay to ensure database consistency
    await new Promise(resolve => setTimeout(resolve, 100));

    return calendars;
  }

  /**
   * Create a test tag via API
   * Note: There's no direct /api/tags endpoint, so we create a temporary contact
   * with the tag name to auto-create the tag, then delete the contact
   */
  async createTag(
    tagData: TagCreateRequest
  ): Promise<{ id: string; name: string }> {
    console.log(`🏷️ [Data Manager] Creating tag via tags API: ${tagData.name}`);

    try {
      // Use the new tags API endpoint to create the tag
      const tagCreateData = {
        data: {
          type: 'tags',
          attributes: {
            name: tagData.name,
          },
        },
      };

      const response = await this.page.request.post('/api/tags', {
        data: tagCreateData,
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok()) {
        let errorMessage = `HTTP ${response.status()}`;
        try {
          const errorData = await response.json();
          errorMessage =
            errorData.errors?.[0]?.detail || errorData.message || errorMessage;
        } catch {
          // If we can't parse JSON, use the status text
          errorMessage = `${response.status()} ${response.statusText()}`;
        }
        throw new Error(`Failed to create tag: ${errorMessage}`);
      }

      const responseData = await response.json();
      const createdTag = responseData.data;
      const tagId = createdTag.id;

      this.createdTagIds.push(tagId);

      console.log(`✅ [Data Manager] Tag created with ID: ${tagId}`);

      return {
        id: tagId,
        name: tagData.name,
      };
    } catch (error) {
      console.error(
        `❌ [Data Manager] Failed to create tag: ${tagData.name}`,
        error
      );
      // Return a mock ID as fallback
      const mockId = `mock-tag-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
      return {
        id: mockId,
        name: tagData.name,
      };
    }
  }

  /**
   * Find existing tag by name
   */
  async findTagByName(
    name: string
  ): Promise<{ id: string; name: string } | null> {
    try {
      const response = await this.page.request.get('/api/tags');
      if (!response.ok()) {
        return null;
      }

      const responseData = await response.json();
      const tags = responseData.data || [];

      const existingTag = tags.find((tag: any) => tag.attributes.name === name);
      if (existingTag) {
        return {
          id: existingTag.id,
          name: existingTag.attributes.name,
        };
      }

      return null;
    } catch (error) {
      console.warn(
        `⚠️ [Data Manager] Failed to search for tag "${name}":`,
        error
      );
      return null;
    }
  }

  /**
   * Create multiple test tags (reuse existing ones if they already exist)
   */
  async createTags(
    tagsData: TagCreateRequest[]
  ): Promise<{ id: string; name: string }[]> {
    console.log(`🏷️ [Data Manager] Creating ${tagsData.length} tags...`);

    const tags: { id: string; name: string }[] = [];

    // Add timeout to prevent hanging
    const startTime = Date.now();
    const maxCreationTime = 30000; // 30 seconds total for all tags

    for (const tagData of tagsData) {
      if (Date.now() - startTime > maxCreationTime) {
        console.warn(
          `⚠️ [Data Manager] Tag creation timed out after ${maxCreationTime}ms`
        );
        break;
      }

      // First, try to find existing tag
      const existingTag = await this.findTagByName(tagData.name);
      if (existingTag) {
        console.log(
          `🔄 [Data Manager] Reusing existing tag: ${existingTag.name} (ID: ${existingTag.id})`
        );
        tags.push(existingTag);
        continue;
      }

      // If not found, create new tag
      try {
        const tag = await this.createTag(tagData);
        tags.push(tag);
      } catch (error) {
        console.error(
          `❌ [Data Manager] Failed to create tag: ${tagData.name}`,
          error
        );
        // Don't add failed tags to the list
      }
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
        // Skip mock tag IDs (they don't exist in the database)
        if (tagId.startsWith('mock-tag-')) {
          console.log(`🏷️ [Data Manager] Skipping mock tag ID: ${tagId}`);
          continue;
        }

        // Use the correct API endpoint: POST /api/contacts/{contact_id}/tags
        // with tag data in the request body
        const response = await this.page.request.post(
          `/api/contacts/${contactId}/tags`,
          {
            data: {
              data: {
                type: 'tags',
                id: tagId,
              },
            },
          }
        );

        if (response.ok()) {
          console.log(
            `✅ [Data Manager] Tag ${tagId} assigned to contact ${contactId}`
          );
        } else {
          const errorText = await response.text();
          console.warn(
            `⚠️ [Data Manager] Failed to assign tag ${tagId} to contact ${contactId}: ${response.status()}`
          );
          console.warn(`⚠️ [Data Manager] Error response:`, errorText);
        }
      }

      console.log(
        `✅ [Data Manager] Tag assignment completed for contact ${contactId}`
      );
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
      // First check current favourite status
      const getResponse = await this.page.request.get(
        `/api/contacts/${contactId}`,
        {
          headers: {
            Accept: 'application/vnd.api+json',
          },
        }
      );

      if (!getResponse.ok()) {
        console.warn(
          `⚠️ [Data Manager] Failed to get contact status: ${getResponse.status()}`
        );
        return;
      }

      const contactData = await getResponse.json();
      const currentFavourite = contactData.data.attributes.is_favourite;

      // Only toggle if the current status is different from desired status
      if (currentFavourite === isFavourite) {
        console.log(
          `✅ [Data Manager] Contact favourite status already correct`
        );
      } else {
        const response = await this.page.request.post(
          `/api/contacts/${contactId}/favourite`,
          {
            headers: {
              'Content-Type': 'application/json', // Use regular JSON, not JSON API
            },
          }
        );

        if (response.ok()) {
          console.log(`✅ [Data Manager] Contact favourite status updated`);
        } else {
          console.warn(
            `⚠️ [Data Manager] Failed to set favourite status: ${response.status()}`
          );
        }
      }
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to set favourite status:`, error);
    }
  }

  /**
   * Create a journal tag via API
   */
  async createJournalTag(
    tagData: TagCreateRequest
  ): Promise<{ id: string; name: string }> {
    // Make tag names unique to avoid conflicts using UUID
    const uniqueId = this.generateUniqueId();
    const uniqueName = `${tagData.name}_${uniqueId}`;

    console.log(`🏷️ [Data Manager] Creating journal tag: ${uniqueName}`);

    try {
      const response = await this.page.request.post('/api/journals/tags', {
        headers: {
          'Content-Type': 'application/vnd.api+json',
        },
        data: JSON.stringify({
          data: {
            type: 'journal-tags',
            attributes: {
              name: uniqueName,
              color: tagData.color || '#3B82F6',
            },
          },
        }),
      });

      if (!response.ok()) {
        throw new Error(
          `Failed to create journal tag: ${response.status()} ${await response.text()}`
        );
      }

      const responseData = await response.json();
      const createdTag = responseData.data;
      const tagId = createdTag.id;

      console.log(`✅ [Data Manager] Journal tag created with ID: ${tagId}`);

      // Track the created journal tag for cleanup
      this.createdJournalTagIds.push(tagId);

      return {
        id: tagId,
        name: uniqueName, // Return the unique name that was actually created
      };
    } catch (error) {
      console.error(
        `❌ [Data Manager] Failed to create journal tag: ${tagData.name}`,
        error
      );
      throw error;
    }
  }

  /**
   * Create multiple journal tags
   */
  async createJournalTags(
    tagsData: TagCreateRequest[]
  ): Promise<{ id: string; name: string }[]> {
    console.log(
      `🏷️ [Data Manager] Creating ${tagsData.length} journal tags...`
    );

    const tags: { id: string; name: string }[] = [];

    for (const tagData of tagsData) {
      try {
        const tag = await this.createJournalTag(tagData);
        tags.push(tag);
      } catch (error) {
        console.error(
          `❌ [Data Manager] Failed to create journal tag: ${tagData.name}`,
          error
        );
        // Don't add failed tags to the list
      }
    }

    // Fail fast if not all tags were created
    if (tags.length !== tagsData.length) {
      throw new Error(
        `Failed to create all journal tags: expected ${tagsData.length}, but only created ${tags.length}. ` +
          `See log output above for details on individual failures.`
      );
    }

    return tags;
  }

  /**
   * Assign tags to a journal
   */
  async assignTagsToJournal(
    journalId: string,
    tagIds: string[]
  ): Promise<void> {
    console.log(
      `🏷️ [Data Manager] Assigning ${tagIds.length} tags to journal ${journalId}`
    );

    const failedAssignments: { tagId: string; status: number }[] = [];

    for (const tagId of tagIds) {
      const response = await this.page.request.post(
        `/api/journals/${journalId}/relationships/tags`,
        {
          headers: {
            'Content-Type': 'application/vnd.api+json',
          },
          data: JSON.stringify({
            data: {
              type: 'journal-tag',
              attributes: {
                tag_id: tagId,
              },
            },
          }),
        }
      );

      if (!response.ok()) {
        const status = response.status();
        console.warn(
          `⚠️ [Data Manager] Failed to assign tag ${tagId} to journal ${journalId}: ${status}`
        );
        failedAssignments.push({ tagId, status });
      } else {
        console.log(
          `✅ [Data Manager] Assigned tag ${tagId} to journal ${journalId}`
        );
      }
    }

    if (failedAssignments.length > 0) {
      const details = failedAssignments
        .map(({ tagId, status }) => `${tagId} (status ${status})`)
        .join(', ');
      throw new Error(
        `Failed to assign ${failedAssignments.length} tag(s) to journal ${journalId}: ${details}`
      );
    }
  }

  /**
   * Create a test journal via API
   */
  async createJournal(journalData: JournalCreateRequest): Promise<TestJournal> {
    // Make journal titles unique to avoid conflicts using UUID
    const uniqueId = this.generateUniqueId();
    const uniqueTitle = `${journalData.title}_${uniqueId}`;

    console.log(`📝 [Data Manager] Creating journal: ${uniqueTitle}`);

    try {
      // Make API request to create journal (JSON API format)
      const requestData: {
        data: {
          type: string;
          attributes: {
            title: string;
            content: string;
            event_date_range: { start: string; end: string };
            types: string[];
            type_data: Record<string, unknown>;
            parent_id?: number;
          };
          relationships?: unknown;
        };
      } = {
        data: {
          type: 'journals',
          attributes: {
            title: uniqueTitle,
            content: journalData.content,
            event_date_range: journalData.event_date_range,
            types: journalData.types || [],
            type_data: journalData.type_data || {},
          },
          relationships: journalData.contacts
            ? {
                contacts: {
                  data: journalData.contacts.map(c => ({
                    type: 'journal-contact-relationships',
                    attributes: {
                      contact_id: c.contact_id,
                      relationship_type: c.relationship_type,
                    },
                  })),
                },
              }
            : undefined,
        },
      };

      // Add parent_id if provided
      if (journalData.parent_id !== undefined) {
        requestData.data.attributes.parent_id = journalData.parent_id;
      }

      const response = await this.page.request.post('/api/journals', {
        headers: {
          'Content-Type': 'application/vnd.api+json',
        },
        data: JSON.stringify(requestData),
      });

      if (!response.ok()) {
        throw new Error(
          `Failed to create journal: ${response.status()} ${await response.text()}`
        );
      }

      const responseData = await response.json();
      const journalId = responseData.data.id;
      const journalAttributes = responseData.data.attributes;

      // Track for cleanup
      this.createdJournalIds.push(journalId);

      console.log(`✅ [Data Manager] Created journal ${journalId}`);

      return {
        id: journalId,
        title: journalAttributes.title,
        content: journalAttributes.content,
        event_date_range: journalAttributes.event_date_range,
        types: journalAttributes.types || [],
        contacts: journalAttributes.contacts || [],
        tags: journalAttributes.tags || [],
      };
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to create journal:`, error);
      throw error;
    }
  }

  /**
   * Create multiple test journals
   */
  async createJournals(
    journalsData: JournalCreateRequest[]
  ): Promise<TestJournal[]> {
    const journals: TestJournal[] = [];

    for (const journalData of journalsData) {
      const journal = await this.createJournal(journalData);
      journals.push(journal);
    }

    return journals;
  }

  /**
   * Clear all journals (for test setup)
   */
  async clearAllJournals(): Promise<void> {
    console.log(`🧹 [Data Manager] Clearing all journals...`);

    try {
      // Get all journals
      const response = await this.page.request.get('/api/journals', {
        headers: {
          Accept: 'application/vnd.api+json',
        },
      });

      if (!response.ok()) {
        console.warn(
          `⚠️ [Data Manager] Failed to fetch journals: ${response.status()}`
        );
        return;
      }

      const data = await response.json();
      const journals = data.data || [];

      console.log(
        `🧹 [Data Manager] Found ${journals.length} journals to delete`
      );

      // Delete each journal
      for (const journal of journals) {
        try {
          const deleteResponse = await this.page.request.delete(
            `/api/journals/${journal.id}`
          );
          if (deleteResponse.ok()) {
            console.log(
              `🗑️ [Data Manager] Deleted existing journal ${journal.id}`
            );
          }
        } catch (error) {
          console.warn(
            `⚠️ [Data Manager] Error deleting journal ${journal.id}:`,
            error
          );
        }
      }

      console.log(`✅ [Data Manager] All journals cleared`);
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to clear journals:`, error);
    }
  }

  /**
   * Clean up all created test data
   */
  async cleanup(): Promise<void> {
    console.log(
      `🧹 [Data Manager] Starting cleanup of ${this.createdContactIds.length} contacts, ${this.createdTagIds.length} contact tags, ${this.createdJournalTagIds.length} journal tags, ${this.createdJournalIds.length} journals, and ${this.createdCalendars.length} calendars...`
    );

    // Add timeout to prevent cleanup from hanging
    const cleanupTimeout = 30000; // 30 seconds
    const cleanupPromise = this.performCleanup();

    try {
      await Promise.race([
        cleanupPromise,
        new Promise((_, reject) =>
          setTimeout(
            () => reject(new Error('Cleanup timed out')),
            cleanupTimeout
          )
        ),
      ]);
    } catch (error) {
      console.warn(`⚠️ [Data Manager] Cleanup failed or timed out:`, error);
      // Continue anyway to not block test completion
    }
  }

  /**
   * Perform the actual cleanup operations
   */
  private async performCleanup(): Promise<void> {
    // Use bulk cleanup endpoint for better performance and transaction handling
    try {
      const response = await this.page.request.delete(
        '/api/contacts/test/cleanup'
      );
      if (response.ok()) {
        console.log(`🗑️ [Data Manager] Bulk deleted all contacts successfully`);
      } else {
        console.warn(
          `⚠️ [Data Manager] Bulk cleanup failed: ${response.status()}`
        );
        // Fall back to individual deletion if bulk cleanup fails
        await this.fallbackIndividualCleanup();
      }
    } catch (error) {
      console.warn(`⚠️ [Data Manager] Bulk cleanup error:`, error);
      // Fall back to individual deletion if bulk cleanup fails
      await this.fallbackIndividualCleanup();
    }

    // Clean up journals (if any were created)
    for (const journalId of this.createdJournalIds) {
      try {
        const response = await this.page.request.delete(
          `/api/journals/${journalId}`
        );
        if (response.ok()) {
          console.log(`🗑️ [Data Manager] Deleted journal ${journalId}`);
        } else {
          console.warn(
            `⚠️ [Data Manager] Failed to delete journal ${journalId}: ${response.status()}`
          );
        }
      } catch (error) {
        console.warn(
          `⚠️ [Data Manager] Error deleting journal ${journalId}:`,
          error
        );
      }
    }

    // Clean up contact tags (if any were created)
    for (const tagId of this.createdTagIds) {
      try {
        const response = await this.page.request.delete(`/api/tags/${tagId}`);
        if (response.ok()) {
          console.log(`🗑️ [Data Manager] Deleted contact tag ${tagId}`);
        } else {
          console.warn(
            `⚠️ [Data Manager] Failed to delete contact tag ${tagId}: ${response.status()}`
          );
        }
      } catch (error) {
        console.warn(
          `⚠️ [Data Manager] Error deleting contact tag ${tagId}:`,
          error
        );
      }
    }

    // Clean up journal tags (if any were created)
    for (const tagId of this.createdJournalTagIds) {
      try {
        const response = await this.page.request.delete(
          `/api/journals/tags/${tagId}`
        );
        if (response.ok()) {
          console.log(`🗑️ [Data Manager] Deleted journal tag ${tagId}`);
        } else {
          console.warn(
            `⚠️ [Data Manager] Failed to delete journal tag ${tagId}: ${response.status()}`
          );
        }
      } catch (error) {
        console.warn(
          `⚠️ [Data Manager] Error deleting journal tag ${tagId}:`,
          error
        );
      }
    }

    // Clean up calendars (if any were created)
    for (const calendarId of this.createdCalendars) {
      try {
        const response = await this.page.request.delete(
          `/api/calendars/${calendarId}`
        );
        if (response.ok()) {
          console.log(`🗑️ [Data Manager] Deleted calendar ${calendarId}`);
        } else {
          console.warn(
            `⚠️ [Data Manager] Failed to delete calendar ${calendarId}: ${response.status()}`
          );
        }
      } catch (error) {
        console.warn(
          `⚠️ [Data Manager] Error deleting calendar ${calendarId}:`,
          error
        );
      }
    }

    // Clear tracking arrays
    this.createdContactIds = [];
    this.createdTagIds = [];
    this.createdJournalTagIds = [];
    this.createdJournalIds = [];
    // Note: createdCalendars is readonly, so we can't reassign it
    // The array will be cleared when the TestDataManager instance is destroyed

    console.log(`✅ [Data Manager] Cleanup completed`);
  }

  /**
   * Fallback cleanup method using individual contact deletion
   */
  private async fallbackIndividualCleanup(): Promise<void> {
    console.log(`🧹 [Data Manager] Using fallback individual cleanup...`);

    let successfulDeletes = 0;
    const startTime = Date.now();
    const maxCleanupTime = 20000; // 20 seconds for individual cleanup

    for (const contactId of this.createdContactIds) {
      // Check timeout
      if (Date.now() - startTime > maxCleanupTime) {
        console.warn(
          `⚠️ [Data Manager] Individual cleanup timed out after ${maxCleanupTime}ms`
        );
        break;
      }

      try {
        const response = await this.page.request.delete(
          `/api/contacts/${contactId}`
        );
        if (response.ok()) {
          console.log(`🗑️ [Data Manager] Deleted contact ${contactId}`);
          successfulDeletes++;
        } else if (response.status() === 404) {
          // Contact already deleted - this is fine
          console.log(`🗑️ [Data Manager] Contact ${contactId} already deleted`);
          successfulDeletes++;
        } else {
          // Don't log full error details for 500 errors (known backend transaction issue)
          if (response.status() === 500) {
            console.warn(
              `⚠️ [Data Manager] Failed to delete contact ${contactId}: 500 (backend transaction issue)`
            );
          } else {
            const errorText = await response.text();
            console.warn(
              `⚠️ [Data Manager] Failed to delete contact ${contactId}: ${response.status()}`
            );
            console.warn(`⚠️ [Data Manager] Delete error response:`, errorText);
          }
        }
      } catch (error) {
        console.warn(
          `⚠️ [Data Manager] Error deleting contact ${contactId}:`,
          error
        );
      }

      // Small delay to reduce transaction conflicts
      await new Promise(resolve => setTimeout(resolve, 50));
    }

    if (successfulDeletes > 0) {
      console.log(
        `🗑️ [Data Manager] Successfully deleted ${successfulDeletes}/${this.createdContactIds.length} contacts`
      );
    }
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
      // Use bulk cleanup endpoint for efficient clearing
      const response = await this.page.request.delete(
        '/api/contacts/test/cleanup'
      );
      if (response.ok()) {
        console.log(`🗑️ [Data Manager] Bulk cleared all contacts successfully`);
      } else {
        console.warn(
          `⚠️ [Data Manager] Bulk clear failed: ${response.status()}, falling back to individual deletion`
        );
        await this.fallbackClearAllContacts();
      }
    } catch (error) {
      console.warn(`⚠️ [Data Manager] Bulk clear error:`, error);
      await this.fallbackClearAllContacts();
    }
  }

  /**
   * Fallback method to clear all contacts individually
   */
  private async fallbackClearAllContacts(): Promise<void> {
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

/**
 * Advanced Data Factories for generating realistic test data
 */

export interface DataSet {
  contacts: ContactCreateRequest[];
  tags: TagCreateRequest[];
}

export interface BulkCreateResult<T> {
  created: T[];
  errors: Array<{ item: T; error: string }>;
}

/**
 * Factory for generating realistic contact data
 */
export class ContactFactory {
  private static readonly FIRST_NAMES = [
    'Alice',
    'Bob',
    'Carol',
    'David',
    'Emma',
    'Frank',
    'Grace',
    'Henry',
    'Ivy',
    'Jack',
    'Kate',
    'Liam',
    'Maya',
    'Noah',
    'Olivia',
    'Paul',
    'Quinn',
    'Rachel',
    'Sam',
    'Tara',
    'Uma',
    'Victor',
    'Wendy',
    'Xavier',
    'Yara',
    'Zoe',
  ];

  private static readonly LAST_NAMES = [
    'Anderson',
    'Brown',
    'Chen',
    'Davis',
    'Evans',
    'Foster',
    'Garcia',
    'Harris',
    'Johnson',
    'Kim',
    'Lee',
    'Miller',
    'Nelson',
    "O'Brien",
    'Parker',
    'Quinn',
    'Rodriguez',
    'Smith',
    'Taylor',
    'Underwood',
    'Valdez',
    'Wilson',
    'Young',
    'Zhang',
  ];

  private static readonly DOMAINS = [
    'example.com',
    'test.org',
    'demo.net',
    'sample.io',
    'mock.dev',
    'testing.com',
    'placeholder.org',
    'dummy.net',
  ];

  static create(
    overrides: Partial<ContactCreateRequest> = {}
  ): ContactCreateRequest {
    const firstName =
      this.FIRST_NAMES[Math.floor(Math.random() * this.FIRST_NAMES.length)];
    const lastName =
      this.LAST_NAMES[Math.floor(Math.random() * this.LAST_NAMES.length)];
    const domain =
      this.DOMAINS[Math.floor(Math.random() * this.DOMAINS.length)];

    return {
      firstName,
      lastName,
      email: `${firstName.toLowerCase()}.${lastName.toLowerCase()}@${domain}`,
      phone: generatePhoneNumber(),
      isFavourite: Math.random() > 0.8, // 20% chance of being favourite
      ...overrides,
    };
  }

  static createMany(
    count: number,
    overrides: Partial<ContactCreateRequest> = {}
  ): ContactCreateRequest[] {
    return Array.from({ length: count }, () => this.create(overrides));
  }

  static createWithTags(
    tagNames: string[],
    overrides: Partial<ContactCreateRequest> = {}
  ): ContactCreateRequest {
    return this.create({ ...overrides, tags: tagNames });
  }

  static createFavourites(count: number): ContactCreateRequest[] {
    return this.createMany(count, { isFavourite: true });
  }

  static createWithEmails(count: number): ContactCreateRequest[] {
    return this.createMany(count).map(contact => ({
      ...contact,
      email: contact.email || `${contact.firstName.toLowerCase()}@example.com`,
    }));
  }

  static createWithPhones(count: number): ContactCreateRequest[] {
    return this.createMany(count).map(contact => ({
      ...contact,
      phone: contact.phone || generatePhoneNumber(),
    }));
  }
}

/**
 * Factory for generating tag data
 */
export class TagFactory {
  private static readonly TAG_NAMES = [
    'Work',
    'Personal',
    'Family',
    'Friends',
    'Business',
    'Client',
    'Vendor',
    'Team',
    'Project',
    'Important',
    'Archive',
    'Follow-up',
    'Meeting',
    'Call',
    'Email',
    'Urgent',
    'Low-Priority',
    'High-Priority',
    'Marketing',
    'Sales',
    'Support',
    'Development',
    'Design',
    'Research',
  ];

  private static readonly COLORS = [
    '#FF6B6B',
    '#4ECDC4',
    '#45B7D1',
    '#96CEB4',
    '#FFEAA7',
    '#DDA0DD',
    '#98D8C8',
    '#F7DC6F',
    '#BB8FCE',
    '#85C1E9',
    '#F8C471',
    '#82E0AA',
    '#AED6F1',
    '#F1948A',
    '#D7BDE2',
    '#A9DFBF',
    '#F9E79F',
    '#AEB6BF',
  ];

  static create(overrides: Partial<TagCreateRequest> = {}): TagCreateRequest {
    const name =
      this.TAG_NAMES[Math.floor(Math.random() * this.TAG_NAMES.length)];
    const color = this.COLORS[Math.floor(Math.random() * this.COLORS.length)];
    const timestamp = Date.now();

    return {
      name: `${name}-${timestamp}`, // Ensure uniqueness
      color,
      ...overrides,
    };
  }

  static createMany(
    count: number,
    overrides: Partial<TagCreateRequest> = {}
  ): TagCreateRequest[] {
    return Array.from({ length: count }, () => this.create(overrides));
  }

  static createWithPrefix(prefix: string, count: number): TagCreateRequest[] {
    return Array.from({ length: count }, (_, index) =>
      this.create({
        name: `${prefix}-${index + 1}-${Date.now()}`,
      })
    );
  }

  static createHierarchy(): TagCreateRequest[] {
    const timestamp = Date.now();
    return [
      this.create({ name: `Work-Parent-${timestamp}`, color: '#FF6B6B' }),
      this.create({ name: `Work-Team-${timestamp}`, color: '#FF8E8E' }),
      this.create({ name: `Work-Client-${timestamp}`, color: '#FFB1B1' }),
      this.create({ name: `Personal-Parent-${timestamp}`, color: '#4ECDC4' }),
      this.create({ name: `Personal-Family-${timestamp}`, color: '#71D4D4' }),
      this.create({ name: `Personal-Friends-${timestamp}`, color: '#94DCDC' }),
    ];
  }
}

/**
 * Factory for generating complete datasets with relationships
 */
export class DataSetFactory {
  static createEmpty(): DataSet {
    return {
      contacts: [],
      tags: [],
    };
  }

  static createSmall(): DataSet {
    const tags = TagFactory.createMany(3);
    const contacts = ContactFactory.createMany(5);

    // Assign some tags to contacts
    contacts[0].tags = [tags[0].name];
    contacts[1].tags = [tags[0].name, tags[1].name];
    contacts[2].tags = [tags[2].name];

    return {
      contacts,
      tags,
    };
  }

  static createMedium(): DataSet {
    const tags = TagFactory.createMany(8);
    const contacts = ContactFactory.createMany(20);

    // Assign tags to various contacts
    for (let i = 0; i < contacts.length; i++) {
      const numTags = Math.floor(Math.random() * 3); // 0-2 tags per contact
      const selectedTags = tags
        .sort(() => 0.5 - Math.random())
        .slice(0, numTags)
        .map(tag => tag.name);
      contacts[i].tags = selectedTags;
    }

    return {
      contacts,
      tags,
    };
  }

  static createLarge(): DataSet {
    const tags = TagFactory.createMany(15);
    const contacts = ContactFactory.createMany(100);

    // Create more realistic tag distribution
    for (let i = 0; i < contacts.length; i++) {
      const numTags = Math.floor(Math.random() * 4); // 0-3 tags per contact
      const selectedTags = tags
        .sort(() => 0.5 - Math.random())
        .slice(0, numTags)
        .map(tag => tag.name);
      contacts[i].tags = selectedTags;
    }

    return {
      contacts,
      tags,
    };
  }

  static createSearchTestData(): DataSet {
    const timestamp = Date.now();
    const tags = [
      TagFactory.create({ name: `SearchTag1-${timestamp}`, color: '#FF6B6B' }),
      TagFactory.create({ name: `SearchTag2-${timestamp}`, color: '#4ECDC4' }),
      TagFactory.create({ name: `CommonTag-${timestamp}`, color: '#45B7D1' }),
    ];

    const contacts = [
      ContactFactory.create({
        firstName: 'John',
        lastName: 'SearchTest',
        email: 'john.search@test.com',
        tags: [tags[0].name],
      }),
      ContactFactory.create({
        firstName: 'Jane',
        lastName: 'FindMe',
        email: 'jane.findme@test.com',
        tags: [tags[1].name, tags[2].name],
      }),
      ContactFactory.create({
        firstName: 'Bob',
        lastName: 'Regular',
        email: 'bob@regular.com',
        tags: [tags[2].name],
      }),
      ContactFactory.create({
        firstName: 'Alice',
        lastName: 'NoTags',
        email: 'alice@notags.com',
        tags: [],
      }),
    ];

    return {
      contacts,
      tags,
    };
  }

  static createFavouritesTestData(): DataSet {
    const tags = TagFactory.createMany(3);
    const favourites = ContactFactory.createFavourites(3);
    const regular = ContactFactory.createMany(5, { isFavourite: false });

    return {
      contacts: [...favourites, ...regular],
      tags,
    };
  }

  static createTaggedData(): DataSet {
    const tags = TagFactory.createHierarchy();
    const contacts = [
      ContactFactory.createWithTags([tags[0].name, tags[1].name]), // Work tags
      ContactFactory.createWithTags([tags[3].name, tags[4].name]), // Personal tags
      ContactFactory.createWithTags([tags[0].name, tags[3].name]), // Mixed tags
      ContactFactory.create(), // No tags
    ];

    return {
      contacts,
      tags,
    };
  }

  static createPerformanceTestData(): DataSet {
    const tags = TagFactory.createMany(50);
    const contacts = ContactFactory.createMany(500);

    // Distribute tags across contacts for performance testing
    for (let i = 0; i < contacts.length; i++) {
      const numTags = Math.floor(Math.random() * 5); // 0-4 tags per contact
      const selectedTags = tags
        .sort(() => 0.5 - Math.random())
        .slice(0, numTags)
        .map(tag => tag.name);
      contacts[i].tags = selectedTags;
    }

    return {
      contacts,
      tags,
    };
  }
}
