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
  importantDates?: Array<{
    date_type: string;
    precision: string;
    year?: number;
    month?: number;
    day?: number;
  }>;
}

export interface TagCreateRequest {
  name: string;
  color?: string;
  parent_id?: number | null;
}

/** Journal tags are UUID-keyed, so their parent reference is a string. */
export interface JournalTagCreateRequest {
  name: string;
  color?: string;
  parent_id?: string;
}

export interface CalendarCreateRequest {
  name: string;
  color?: string;
  description?: string;
}

export interface JournalCreateRequest {
  title: string;
  exactTitle?: boolean;
  content: string;
  event_date_range: {
    start: string;
    end: string;
  };
  types?: string[];
  type_data?: Record<string, unknown>;
  contacts?: Array<{
    contact_id: string;
    relationship_type: string;
    status?: string | null;
    role?: string | null;
  }>;
  tags?: string[];
  calendar_id?: string;
  // Note: Journal IDs are integers (SERIAL in database), not UUIDs
  // This is different from calendars and tags which use UUIDs
  parent_id?: number;
}

export interface ReviewItemCreateRequest {
  source_journal_id: number;
  candidate_journal_id: number;
  reason?: string;
  confidence_score?: number;
  details?: Record<string, unknown>;
}

/**
 * Manages test data creation and cleanup via API calls
 */
export class TestDataManager {
  private createdContactIds: string[] = [];
  private createdTagIds: string[] = []; // Contact tags
  private createdJournalTagIds: string[] = []; // Journal tags
  private createdJournalIds: string[] = [];
  private createdGearItemIds: string[] = [];
  private createdTemplateIds: string[] = [];
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

    console.debug(
      `📝 [Data Manager] Creating contact: ${uniqueFirstName} ${uniqueLastName}`
    );

    try {
      // Debug: Check authentication and cookies
      // Verify authentication applies - only run if debugging is enabled
      // The actual auth validation is done in the fixtures
      if (process.env.DEBUG_E2E) {
        const authTestResponse =
          await this.page.request.get('/api/auth/status');
        if (authTestResponse.ok()) {
          const authData = await authTestResponse.json();
          console.debug(`🔐 [Data Manager] Auth test successful:`, authData);
        } else {
          console.debug(
            `🔐 [Data Manager] Auth test failed: ${authTestResponse.status()}`
          );
          const errorText = await authTestResponse.text();
          console.debug(`🔐 [Data Manager] Auth error response:`, errorText);
          const contextCookies = await this.page.context().cookies();
          console.debug(
            `🔐 [Data Manager] Context has ${contextCookies.length} cookies:`,
            contextCookies.map(c => c.name).join(', ')
          );
        }
      }

      // Make API request to create contact (JSON API format)
      // Note: Simplified to avoid contact methods for now due to transaction issues
      const attributes: {
        first_name: string;
        last_name: string;
        is_favourite: boolean;
        important_dates?: Array<{
          attributes: {
            date_type: string;
            precision: string;
            year?: number;
            month?: number;
            day?: number;
          };
        }>;
      } = {
        first_name: uniqueFirstName,
        last_name: uniqueLastName,
        is_favourite: contactData.isFavourite || false,
      };

      if (contactData.importantDates) {
        attributes.important_dates = contactData.importantDates.map(date => ({
          attributes: { ...date },
        }));
      }

      const response = await this.page.request.post('/api/contacts', {
        headers: {
          'Content-Type': 'application/json',
        },
        data: JSON.stringify({
          data: {
            type: 'contacts',
            attributes: attributes,
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
        console.debug(
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

      console.debug(
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
        importantDates: contactData.importantDates,
      };
    } catch (error) {
      console.error(`❌ [Data Manager] Failed to create contact:`, error);
      throw error;
    }
  }

  /**
   * Create multiple test contacts
   */
  async createContacts(
    contactsData: ContactCreateRequest[]
  ): Promise<TestContact[]> {
    console.debug(
      `📝 [Data Manager] Creating ${contactsData.length} contacts...`
    );

    const contacts: TestContact[] = [];

    // Add timeout to prevent hanging
    const startTime = Date.now();
    const maxCreationTime = 60000; // 1 minute total for all contacts

    for (const contactData of contactsData) {
      if (Date.now() - startTime > maxCreationTime) {
        console.debug(
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
    console.debug(
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
      console.debug(`✅ [Data Manager] Created calendar: ${calendar.name}`);
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
    console.debug(
      `🏷️ [Data Manager] Creating tag via tags API: ${tagData.name}`
    );

    try {
      // Use the new tags API endpoint to create the tag
      const tagCreateData = {
        data: {
          type: 'tags',
          attributes: {
            name: tagData.name,
            ...(tagData.color ? { color: tagData.color } : {}),
            ...(tagData.parent_id === undefined
              ? {}
              : { parent_id: tagData.parent_id }),
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

      console.debug(`✅ [Data Manager] Tag created with ID: ${tagId}`);

      return {
        id: tagId,
        name: tagData.name,
      };
    } catch (error) {
      console.error(
        `❌ [Data Manager] Failed to create tag: ${tagData.name}`,
        error
      );
      throw error;
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

      const existingTag = tags.find(
        (tag: { attributes?: { name?: string }; id: string }) =>
          tag.attributes?.name === name
      );
      if (existingTag) {
        return {
          id: existingTag.id,
          name: existingTag.attributes!.name!,
        };
      }

      return null;
    } catch (error) {
      console.debug(
        `⚠️ [Data Manager] Failed to search for tag "${name}":`,
        error
      );
      return null;
    }
  }

  /**
   * Delete existing tag by name
   */
  async deleteTagByName(name: string): Promise<void> {
    try {
      const tag = await this.findTagByName(name);
      if (tag) {
        console.debug(
          `🗑️ [Data Manager] Deleting tag "${name}" (ID: ${tag.id})`
        );
        const response = await this.page.request.delete(`/api/tags/${tag.id}`);
        if (!response.ok()) {
          console.debug(
            `⚠️ [Data Manager] Failed to delete tag "${name}": ${response.status()}`
          );
        }
      }
    } catch (error) {
      console.debug(`⚠️ [Data Manager] Error deleting tag "${name}":`, error);
    }
  }

  /**
   * Create multiple test tags (reuse existing ones if they already exist)
   */
  async createTags(
    tagsData: TagCreateRequest[]
  ): Promise<{ id: string; name: string }[]> {
    console.debug(`🏷️ [Data Manager] Creating ${tagsData.length} tags...`);

    const tags: { id: string; name: string }[] = [];

    // Add timeout to prevent hanging
    const startTime = Date.now();
    const maxCreationTime = 30000; // 30 seconds total for all tags

    for (const tagData of tagsData) {
      if (Date.now() - startTime > maxCreationTime) {
        console.debug(
          `⚠️ [Data Manager] Tag creation timed out after ${maxCreationTime}ms`
        );
        break;
      }

      // First, try to find existing tag
      const existingTag = await this.findTagByName(tagData.name);
      if (existingTag) {
        console.debug(
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
        console.debug(
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
    console.debug(
      `🏷️ [Data Manager] Assigning ${tagIds.length} tags to contact ${contactId}`
    );

    try {
      for (const tagId of tagIds) {
        const maxRetries = 3;

        for (let attempt = 1; attempt <= maxRetries; attempt++) {
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
            console.debug(
              `✅ [Data Manager] Tag ${tagId} assigned to contact ${contactId}`
            );
            break;
          }

          const statusCode = response.status();
          const errorText = await response.text();

          if (
            (statusCode === 404 || statusCode >= 500) &&
            attempt < maxRetries
          ) {
            console.debug(
              `⚠️ [Data Manager] Tag assignment attempt ${attempt}/${maxRetries} got ${statusCode}, retrying...`
            );
            await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
            continue;
          }

          console.debug(
            `⚠️ [Data Manager] Failed to assign tag ${tagId} to contact ${contactId}: ${statusCode}`
          );
          console.debug(`⚠️ [Data Manager] Error response:`, errorText);
          break;
        }
      }

      console.debug(
        `✅ [Data Manager] Tag assignment completed for contact ${contactId}`
      );
    } catch (error) {
      console.debug(`❌ [Data Manager] Failed to assign tags:`, error);
    }
  }

  /**
   * Set contact as favourite
   */
  async setContactFavourite(
    contactId: string,
    isFavourite: boolean
  ): Promise<void> {
    console.debug(
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
        console.debug(
          `⚠️ [Data Manager] Failed to get contact status: ${getResponse.status()}`
        );
        return;
      }

      const contactData = await getResponse.json();
      const currentFavourite = contactData.data.attributes.is_favourite;

      // Only toggle if the current status is different from desired status
      if (currentFavourite === isFavourite) {
        console.debug(
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
          console.debug(`✅ [Data Manager] Contact favourite status updated`);
        } else {
          console.debug(
            `⚠️ [Data Manager] Failed to set favourite status: ${response.status()}`
          );
        }
      }
    } catch (error) {
      console.debug(`❌ [Data Manager] Failed to set favourite status:`, error);
    }
  }

  /**
   * Create a relationship between two contacts via API.
   *
   * Retries on transient 404/5xx errors to handle database consistency delays
   * in CI where recently-created contacts may be momentarily invisible.
   */
  async createRelationship(
    fromContactId: string,
    toContactId: string,
    relationshipType: string
  ): Promise<void> {
    console.debug(
      `🔗 [Data Manager] Creating relationship: ${fromContactId} -> ${toContactId} (${relationshipType})`
    );

    const maxRetries = 3;
    let lastError: Error | undefined;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      const response = await this.page.request.post(
        `/api/contacts/${fromContactId}/relationships`,
        {
          headers: {
            'Content-Type': 'application/vnd.api+json',
            Accept: 'application/vnd.api+json',
          },
          data: {
            data: {
              type: 'contact_relationships',
              attributes: {
                from_contact_id: Number(fromContactId),
                to_contact_id: Number(toContactId),
                relationship_type: relationshipType,
              },
            },
          },
        }
      );

      if (response.ok()) {
        console.debug(
          `✅ [Data Manager] Relationship created: ${fromContactId} -> ${toContactId}`
        );
        return;
      }

      const statusCode = response.status();
      const errorBody = await response.text();

      // Retry on transient errors (404 = contact not yet visible, 5xx = server)
      if ((statusCode === 404 || statusCode >= 500) && attempt < maxRetries) {
        console.debug(
          `⚠️ [Data Manager] Relationship creation attempt ${attempt}/${maxRetries} ` +
            `got ${statusCode}, retrying after delay...`
        );
        await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        lastError = new Error(
          `Failed to create relationship: ${statusCode} - ${errorBody}`
        );
        continue;
      }

      // Non-retryable error or final attempt — throw immediately
      throw new Error(
        `Failed to create relationship: ${statusCode} - ${errorBody}`
      );
    }

    // Should not reach here, but satisfy TypeScript
    throw lastError ?? new Error('Failed to create relationship after retries');
  }

  /**
   * Create a user-targeted relationship via API.
   *
   * Creates a relationship where the target is "You" (the current user)
   * rather than another contact.
   * Retries on transient 404/5xx errors to handle database consistency delays.
   */
  async createUserRelationship(
    fromContactId: string,
    relationshipType: string
  ): Promise<void> {
    console.debug(
      `🔗 [Data Manager] Creating user-targeted relationship: ${fromContactId} -> You (${relationshipType})`
    );

    const maxRetries = 3;
    let lastError: Error | undefined;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      const response = await this.page.request.post(
        `/api/contacts/${fromContactId}/relationships`,
        {
          headers: {
            'Content-Type': 'application/vnd.api+json',
            Accept: 'application/vnd.api+json',
          },
          data: {
            data: {
              type: 'contact_relationships',
              attributes: {
                from_contact_id: Number(fromContactId),
                to_user: true,
                relationship_type: relationshipType,
              },
            },
          },
        }
      );

      if (response.ok()) {
        console.debug(
          `✅ [Data Manager] User-targeted relationship created: ${fromContactId} -> You`
        );
        return;
      }

      const statusCode = response.status();
      const errorBody = await response.text();

      // Retry on transient errors (404 = contact not yet visible, 5xx = server)
      if ((statusCode === 404 || statusCode >= 500) && attempt < maxRetries) {
        console.debug(
          `⚠️ [Data Manager] User relationship creation attempt ${attempt}/${maxRetries} ` +
            `got ${statusCode}, retrying after delay...`
        );
        await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        lastError = new Error(
          `Failed to create user-targeted relationship: ${statusCode} - ${errorBody}`
        );
        continue;
      }

      // Non-retryable error or final attempt — throw immediately
      throw new Error(
        `Failed to create user-targeted relationship: ${statusCode} - ${errorBody}`
      );
    }

    // Should not reach here, but satisfy TypeScript
    throw (
      lastError ??
      new Error('Failed to create user-targeted relationship after retries')
    );
  }

  /**
   * Create a journal tag via API
   *
   * Journal tags use UUID primary keys, so `parent_id` is a string here rather
   * than the numeric contact-tag id in {@link TagCreateRequest}.
   */
  async createJournalTag(
    tagData: JournalTagCreateRequest
  ): Promise<{ id: string; name: string }> {
    // Make tag names unique to avoid conflicts using UUID
    const uniqueId = this.generateUniqueId();
    const uniqueName = `${tagData.name}_${uniqueId}`;

    console.debug(`🏷️ [Data Manager] Creating journal tag: ${uniqueName}`);

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
              ...(tagData.parent_id ? { parent_id: tagData.parent_id } : {}),
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

      console.debug(`✅ [Data Manager] Journal tag created with ID: ${tagId}`);

      // Track the created journal tag for cleanup
      this.createdJournalTagIds.push(tagId);

      return {
        id: tagId,
        name: uniqueName, // Return the unique name that was actually created
      };
    } catch (error) {
      console.debug(
        `❌ [Data Manager] Failed to create journal tag: ${tagData.name}`,
        error
      );
      throw error;
    }
  }

  /**
   * Track a journal tag this manager did not create itself, so it is deleted by
   * {@link cleanup}. Used when a test creates a tag *through the UI* (the inline
   * create-and-assign flow) — without this the tag would be orphaned in the
   * shared journal tag namespace and leak into other tests' tag lists.
   */
  trackJournalTag(tagId: string): void {
    this.createdJournalTagIds.push(tagId);
  }

  /**
   * Create multiple journal tags
   */
  async createJournalTags(
    tagsData: JournalTagCreateRequest[]
  ): Promise<{ id: string; name: string }[]> {
    console.debug(
      `🏷️ [Data Manager] Creating ${tagsData.length} journal tags...`
    );

    const tags: { id: string; name: string }[] = [];

    for (const tagData of tagsData) {
      try {
        const tag = await this.createJournalTag(tagData);
        tags.push(tag);
      } catch (error) {
        console.debug(
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
    console.debug(
      `🏷️ [Data Manager] Assigning ${tagIds.length} tags to journal ${journalId}`
    );

    const failedAssignments: { tagId: string; status: number }[] = [];

    for (const tagId of tagIds) {
      const maxRetries = 3;
      let success = false;
      let lastStatus = 0;

      for (let attempt = 1; attempt <= maxRetries; attempt++) {
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

        if (response.ok()) {
          console.debug(
            `✅ [Data Manager] Assigned tag ${tagId} to journal ${journalId}`
          );
          success = true;
          break;
        }

        const status = response.status();
        lastStatus = status;

        if ((status === 404 || status >= 500) && attempt < maxRetries) {
          console.debug(
            `⚠️ [Data Manager] Journal tag assignment attempt ${attempt}/${maxRetries} got ${status}, retrying...`
          );
          await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
          continue;
        }

        console.debug(
          `⚠️ [Data Manager] Failed to assign tag ${tagId} to journal ${journalId}: ${status}`
        );
        break;
      }

      if (!success) {
        failedAssignments.push({ tagId, status: lastStatus });
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
    // Use exact title if requested, or bypass if it already ends with _ followed by an alphanumeric ID
    const uniqueTitle =
      journalData.exactTitle || /_[a-z0-9]{8,12}$/i.test(journalData.title)
        ? journalData.title
        : `${journalData.title}_${uniqueId}`;

    console.debug(`📝 [Data Manager] Creating journal: ${uniqueTitle}`);

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
                      ...(c.status !== undefined && { status: c.status }),
                      ...(c.role !== undefined && { role: c.role }),
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

      // Retry loop to handle transient 500 errors (database contention in CI)
      const maxRetries = 3;
      let lastError: Error | undefined;
      for (let attempt = 1; attempt <= maxRetries; attempt++) {
        const response = await this.page.request.post('/api/journals', {
          headers: {
            'Content-Type': 'application/vnd.api+json',
          },
          data: JSON.stringify(requestData),
        });

        if (response.ok()) {
          const responseData = await response.json();
          const journalId = responseData.data.id;
          const journalAttributes = responseData.data.attributes;

          // Added: Verify the journal is readable to handle backend transaction commit delay
          // Dishka FastAPI integrations sometimes commit immediately AFTER the response is sent.
          for (let verifyAttempt = 1; verifyAttempt <= 5; verifyAttempt++) {
            const getResponse = await this.page.request.get(
              `/api/journals/${journalId}`
            );
            if (getResponse.ok()) {
              break;
            }
            await new Promise(resolve =>
              setTimeout(resolve, 50 * verifyAttempt)
            );
          }

          // Track for cleanup
          this.createdJournalIds.push(journalId);

          console.debug(`✅ [Data Manager] Created journal ${journalId}`);

          return {
            id: journalId,
            title: journalAttributes.title,
            content: journalAttributes.content,
            event_date_range: journalAttributes.event_date_range,
            types: journalAttributes.types || [],
            contacts: journalAttributes.contacts || [],
            tags: journalAttributes.tags || [],
          };
        }

        const statusCode = response.status();
        const responseText = await response.text();

        // Retry on server errors (5xx)
        if (statusCode >= 500 && attempt < maxRetries) {
          console.debug(
            `⚠️ [Data Manager] Journal creation attempt ${attempt}/${maxRetries} ` +
              `got ${statusCode}, retrying after delay...`
          );
          await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
          lastError = new Error(
            `Failed to create journal: ${statusCode} ${responseText}`
          );
          continue;
        }

        // Non-retryable error or final attempt — throw immediately
        throw new Error(
          `Failed to create journal: ${statusCode} ${responseText}`
        );
      }

      // Should not reach here, but satisfy TypeScript
      throw lastError ?? new Error('Failed to create journal after retries');
    } catch (error) {
      console.debug(`❌ [Data Manager] Failed to create journal:`, error);
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
   * Create a GPX route attached to a journal via API.
   *
   * Used to set up route test data for verifying route display
   * on journal detail pages.
   */
  async createRoute(
    journalId: string,
    routeData: { name: string; gpx_data: string }
  ): Promise<{ id: string; name: string }> {
    console.debug(
      `🗺️ [Data Manager] Creating route "${routeData.name}" for journal ${journalId}`
    );

    const response = await this.page.request.post(
      `/api/journals/${journalId}/routes`,
      {
        headers: {
          'Content-Type': 'application/vnd.api+json',
          Accept: 'application/vnd.api+json',
        },
        data: JSON.stringify({
          data: {
            type: 'routes',
            attributes: {
              name: routeData.name,
              gpx_data: routeData.gpx_data,
            },
          },
        }),
      }
    );

    if (!response.ok()) {
      const errorText = await response.text();
      throw new Error(
        `Failed to create route: ${response.status()} ${errorText}`
      );
    }

    const responseData = await response.json();
    const routeId = responseData.data.id;

    console.debug(
      `✅ [Data Manager] Created route ${routeId} for journal ${journalId}`
    );

    return { id: routeId, name: routeData.name };
  }

  /**
   * Create a gear item via API.
   *
   * The name is made unique so parallel workers don't collide; the returned
   * name is the one actually stored, for assertions.
   */
  async createGearItem(name: string): Promise<{ id: string; name: string }> {
    const uniqueName = `${name}_${this.generateUniqueId()}`;
    console.debug(`🎒 [Data Manager] Creating gear item "${uniqueName}"`);

    const response = await this.page.request.post('/api/gear-items', {
      data: {
        data: {
          type: 'gear-items',
          attributes: { name: uniqueName },
        },
      },
    });

    if (!response.ok()) {
      const errorText = await response.text();
      throw new Error(
        `Failed to create gear item: ${response.status()} ${errorText}`
      );
    }

    const responseData = await response.json();
    const gearItemId = responseData.data.id;
    this.createdGearItemIds.push(gearItemId);

    console.debug(`✅ [Data Manager] Created gear item ${gearItemId}`);
    return { id: gearItemId, name: uniqueName };
  }

  /**
   * Create an activity template via API.
   *
   * `templateType` is one of the template types (canyoning / caving /
   * climbing / abseiling) — it drives the grouping in the dashboard's
   * templates-done widget.
   */
  async createTemplate(
    name: string,
    templateType: string
  ): Promise<{ id: string; name: string }> {
    const uniqueName = `${name}_${this.generateUniqueId()}`;
    console.debug(
      `📐 [Data Manager] Creating ${templateType} template "${uniqueName}"`
    );

    const response = await this.page.request.post('/api/templates', {
      data: {
        data: {
          type: 'templates',
          attributes: { name: uniqueName, template_type: templateType },
        },
      },
    });

    if (!response.ok()) {
      const errorText = await response.text();
      throw new Error(
        `Failed to create template: ${response.status()} ${errorText}`
      );
    }

    const responseData = await response.json();
    const templateId = responseData.data.id;
    this.createdTemplateIds.push(templateId);

    console.debug(`✅ [Data Manager] Created template ${templateId}`);
    return { id: templateId, name: uniqueName };
  }

  /**
   * Create a GEAR_USAGE journal recording a checkout of `gearItemId`.
   *
   * The checkout window resolves to the journal's event range, so a range
   * spanning "now" is a currently-checked-out item and a past range is not.
   */
  async createGearUsageJournal(options: {
    title: string;
    gearItemId: string;
    start: string;
    end: string;
  }): Promise<TestJournal> {
    return this.createJournal({
      title: options.title,
      content: 'Gear usage seeded for e2e testing',
      event_date_range: { start: options.start, end: options.end },
      types: ['gear_usage'],
      type_data: {
        gear_usage: { gear_item_id: options.gearItemId },
      },
    });
  }

  /**
   * Create an abseiling trip journal carrying a durable template reference.
   *
   * The consolidated `abseiling_trip.template_id` is what the dashboard's
   * templates-done widget counts.
   */
  async createAbseilingJournal(options: {
    title: string;
    templateId: string;
    start: string;
    end: string;
  }): Promise<TestJournal> {
    return this.createJournal({
      title: options.title,
      content: 'Abseiling trip seeded for e2e testing',
      event_date_range: { start: options.start, end: options.end },
      types: ['abseiling_trip'],
      type_data: {
        abseiling_trip: { template_id: options.templateId },
      },
    });
  }

  /**
   * Create a review item for testing
   */
  async createReviewItem(
    request: ReviewItemCreateRequest
  ): Promise<{ id: string }> {
    console.debug(
      `📝 [Data Manager] Creating review item between journals ${request.source_journal_id} and ${request.candidate_journal_id}`
    );

    const payload = {
      data: {
        type: 'review-items',
        attributes: {
          source_journal_id: request.source_journal_id,
          candidate_journal_id: request.candidate_journal_id,
          reason: request.reason || 'potential_duplicate',
          confidence_score: request.confidence_score || 0.85,
          details: request.details || {},
        },
      },
    };

    // Retry loop to handle transient 500 errors (database contention in CI)
    const maxRetries = 3;
    let lastError: Error | undefined;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      const response = await this.page.request.post(
        '/api/journals/review-items',
        {
          data: payload,
        }
      );

      if (response.ok()) {
        const responseData = await response.json();
        return { id: responseData.data.id };
      }

      const statusCode = response.status();
      const errorText = await response.text();

      // Only retry on server errors (5xx)
      if (statusCode >= 500 && attempt < maxRetries) {
        console.debug(
          `⚠️ [Data Manager] Review item creation attempt ${attempt}/${maxRetries} ` +
            `got ${statusCode}, retrying after delay...`
        );
        await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
        lastError = new Error(
          `Failed to create review item: ${statusCode} ${errorText}`
        );
        continue;
      }

      console.error(`Failed to create review item: ${statusCode} ${errorText}`);
      throw new Error(
        `Failed to create review item: ${statusCode} ${errorText}`
      );
    }

    throw lastError ?? new Error('Failed to create review item after retries');
  }

  /**
   * Clear all journals (for test setup)
   */
  async clearAllJournals(): Promise<void> {
    console.debug(`🧹 [Data Manager] Clearing all journals...`);

    try {
      // Get all journals
      const response = await this.page.request.get('/api/journals', {
        headers: {
          Accept: 'application/vnd.api+json',
        },
      });

      if (!response.ok()) {
        console.debug(
          `⚠️ [Data Manager] Failed to fetch journals: ${response.status()}`
        );
        return;
      }

      const data = await response.json();
      const journals = data.data || [];

      console.debug(
        `🧹 [Data Manager] Found ${journals.length} journals to delete`
      );

      // Delete each journal
      for (const journal of journals) {
        try {
          const deleteResponse = await this.page.request.delete(
            `/api/journals/${journal.id}`
          );
          if (deleteResponse.ok()) {
            console.debug(
              `🗑️ [Data Manager] Deleted existing journal ${journal.id}`
            );
          }
        } catch (error) {
          console.debug(
            `⚠️ [Data Manager] Error deleting journal ${journal.id}:`,
            error
          );
        }
      }

      console.debug(`✅ [Data Manager] All journals cleared`);
    } catch (error) {
      console.debug(`❌ [Data Manager] Failed to clear journals:`, error);
    }
  }

  /**
   * Clean up all created test data
   */
  async cleanup(): Promise<void> {
    console.debug(
      `🧹 [Data Manager] Starting cleanup of ${this.createdContactIds.length} contacts, ${this.createdTagIds.length} contact tags, ${this.createdJournalTagIds.length} journal tags, ${this.createdJournalIds.length} journals, ${this.createdCalendars.length} calendars, ${this.createdGearItemIds.length} gear items, and ${this.createdTemplateIds.length} templates...`
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
      console.debug(`⚠️ [Data Manager] Cleanup failed or timed out:`, error);
      // Continue anyway to not block test completion
    }
  }

  private async cleanupSpecificItems(
    items: readonly string[],
    endpointPrefix: string,
    itemName: string
  ): Promise<void> {
    for (const itemId of items) {
      try {
        const response = await this.page.request.delete(
          `${endpointPrefix}/${itemId}`
        );
        if (response.ok()) {
          console.debug(`🗑️ [Data Manager] Deleted ${itemName} ${itemId}`);
        } else {
          console.debug(
            `⚠️ [Data Manager] Failed to delete ${itemName} ${itemId}: ${response.status()}`
          );
        }
      } catch (error) {
        console.debug(
          `⚠️ [Data Manager] Error deleting ${itemName} ${itemId}:`,
          error
        );
      }
    }
  }

  /**
   * Perform the actual cleanup operations
   */
  private async performCleanup(): Promise<void> {
    // Do NOT use the global /api/contacts/test/cleanup endpoint because it deletes ALL contacts
    // for the user, which breaks other tests running in parallel workers.
    // Instead, we explicitly delete the items this DataManager created.
    await this.fallbackIndividualCleanup();

    await this.cleanupSpecificItems(
      this.createdJournalIds,
      '/api/journals',
      'journal'
    );
    await this.cleanupSpecificItems(
      this.createdTagIds,
      '/api/tags',
      'contact tag'
    );
    await this.cleanupSpecificItems(
      this.createdJournalTagIds,
      '/api/journals/tags',
      'journal tag'
    );
    await this.cleanupSpecificItems(
      this.createdCalendars,
      '/api/calendars',
      'calendar'
    );
    // Gear items and templates are referenced by the journals deleted above,
    // so they must be removed after them.
    await this.cleanupSpecificItems(
      this.createdGearItemIds,
      '/api/gear-items',
      'gear item'
    );
    await this.cleanupSpecificItems(
      this.createdTemplateIds,
      '/api/templates',
      'template'
    );

    // Clear tracking arrays
    this.createdContactIds = [];
    this.createdTagIds = [];
    this.createdJournalTagIds = [];
    this.createdJournalIds = [];
    this.createdGearItemIds = [];
    this.createdTemplateIds = [];
    // Note: createdCalendars is readonly, so we can't reassign it
    // The array will be cleared when the TestDataManager instance is destroyed

    console.debug(`✅ [Data Manager] Cleanup completed`);
  }

  /**
   * Fallback cleanup method using individual contact deletion
   * Uses concurrent batches to speed up deletion of large datasets.
   */
  private async fallbackIndividualCleanup(): Promise<void> {
    if (this.createdContactIds.length === 0) return;

    console.debug(
      `🧹 [Data Manager] Deleting ${this.createdContactIds.length} contacts individually...`
    );

    let successfulDeletes = 0;
    const startTime = Date.now();
    const maxCleanupTime = 30000; // 30 seconds for cleanup
    const batchSize = 10; // Delete up to 10 contacts concurrently

    for (let i = 0; i < this.createdContactIds.length; i += batchSize) {
      if (Date.now() - startTime > maxCleanupTime) {
        console.debug(
          `⚠️ [Data Manager] Contact cleanup timed out after ${maxCleanupTime}ms`
        );
        break;
      }

      const batch = this.createdContactIds.slice(i, i + batchSize);

      await Promise.allSettled(
        batch.map(async contactId => {
          try {
            const response = await this.page.request.delete(
              `/api/contacts/${contactId}`
            );
            if (response.ok()) {
              console.debug(`🗑️ [Data Manager] Deleted contact ${contactId}`);
              successfulDeletes++;
            } else if (response.status() === 404) {
              // Contact already deleted - this is fine
              console.debug(
                `🗑️ [Data Manager] Contact ${contactId} already deleted`
              );
              successfulDeletes++;
            } else {
              // Don't log full error details for 500 errors (known backend transaction issue)
              if (response.status() === 500) {
                console.debug(
                  `⚠️ [Data Manager] Failed to delete contact ${contactId}: 500 (backend transaction issue)`
                );
              } else {
                const errorText = await response.text();
                console.debug(
                  `⚠️ [Data Manager] Failed to delete contact ${contactId}: ${response.status()}`
                );
                console.debug(
                  `⚠️ [Data Manager] Delete error response:`,
                  errorText
                );
              }
            }
          } catch (error) {
            console.debug(
              `⚠️ [Data Manager] Error deleting contact ${contactId}:`,
              error
            );
          }

          // Small delay to reduce transaction conflicts
          await new Promise(resolve => setTimeout(resolve, 50));
        })
      );
    }

    if (successfulDeletes > 0) {
      console.debug(
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
    console.debug(`🧹 [Data Manager] Clearing all existing contacts...`);

    try {
      // Use bulk cleanup endpoint for efficient clearing
      const response = await this.page.request.delete(
        '/api/contacts/test/cleanup'
      );
      if (response.ok()) {
        console.debug(
          `🗑️ [Data Manager] Bulk cleared all contacts successfully`
        );
      } else {
        console.debug(
          `⚠️ [Data Manager] Bulk clear failed: ${response.status()}, falling back to individual deletion`
        );
        await this.fallbackClearAllContacts();
      }
    } catch (error) {
      console.debug(`⚠️ [Data Manager] Bulk clear error:`, error);
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
        console.debug(
          `⚠️ [Data Manager] Failed to fetch contacts for cleanup: ${response.status()}`
        );
        return;
      }

      const data = await response.json();
      const contacts = data.data || [];

      console.debug(
        `🧹 [Data Manager] Found ${contacts.length} contacts to delete`
      );

      // Delete each contact
      for (const contact of contacts) {
        try {
          const deleteResponse = await this.page.request.delete(
            `/api/contacts/${contact.id}`
          );
          if (deleteResponse.ok()) {
            console.debug(
              `🗑️ [Data Manager] Deleted existing contact ${contact.id}`
            );
          }
        } catch (error) {
          console.debug(
            `⚠️ [Data Manager] Error deleting contact ${contact.id}:`,
            error
          );
        }
      }

      console.debug(`✅ [Data Manager] All contacts cleared`);
    } catch (error) {
      console.debug(`❌ [Data Manager] Failed to clear contacts:`, error);
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
    const randomStr = Math.random().toString(36).substring(2, 7);
    return Array.from({ length: count }, (_, index) =>
      this.create({
        name: `${prefix}-${index + 1}-${Date.now()}-${randomStr}`,
      })
    );
  }

  static createHierarchy(): TagCreateRequest[] {
    const timestamp = Date.now();
    const randomStr = Math.random().toString(36).substring(2, 7);
    const suffix = `${timestamp}-${randomStr}`;
    return [
      this.create({ name: `Work-Parent-${suffix}`, color: '#FF6B6B' }),
      this.create({ name: `Work-Team-${suffix}`, color: '#FF8E8E' }),
      this.create({ name: `Work-Client-${suffix}`, color: '#FFB1B1' }),
      this.create({ name: `Personal-Parent-${suffix}`, color: '#4ECDC4' }),
      this.create({ name: `Personal-Family-${suffix}`, color: '#71D4D4' }),
      this.create({ name: `Personal-Friends-${suffix}`, color: '#94DCDC' }),
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
