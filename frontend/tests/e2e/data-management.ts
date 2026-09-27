/**
 * Test Data Management
 *
 * Handles creation, modification, and cleanup of test data via API calls.
 * Provides deterministic data setup for fixtures.
 */

import { APIResponse, Page } from '@playwright/test';

import { TestContact, TestJournal, TestTask } from './fixtures';

/**
 * Utility function to generate realistic phone numbers
 */
function generatePhoneNumber(): string {
  return `+1-555-${Math.floor(Math.random() * 900) + 100}-${Math.floor(Math.random() * 9000) + 1000}`;
}

/**
 * An ISO instant `days` whole days from today, at a fixed hour **in UTC**.
 *
 * Fixtures that reason about "future" and "past" must be built from explicit UTC
 * offsets rather than local wall-clock times. The e2e user has no configured
 * timezone, so the backend judges a journal's date by UTC days — which means a
 * journal built from a local midday can land on the *next* UTC day, and a
 * journal meant to be safely in the past can read as today.
 *
 * Midday is the default hour for the same reason: it is the furthest a fixture
 * can sit from either end of its own day.
 */
export function utcDayOffset(days: number, hour: number = 12): string {
  const moment = new Date();
  moment.setUTCDate(moment.getUTCDate() + days);
  moment.setUTCHours(hour, 0, 0, 0);
  return moment.toISOString();
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

/**
 * A task, which can only exist anchored to two journals.
 *
 * `dueJournalId` must name a journal dated **after today**, and "today" for the
 * e2e user is a **UTC** day: they have no configured timezone, so backend day
 * boundaries fall on UTC midnight and a fixture built from local wall-clock
 * noon can read as tomorrow — or as future when a past journal was intended.
 * Build the anchors with {@link TestDataManager.createTaskAnchorJournals},
 * which does the arithmetic in UTC.
 */
export interface TaskCreateRequest {
  creatingJournalId: string;
  dueJournalId: string;
  text: string;
  /** Contacts to link at creation time. Omitted means none. */
  contactIds?: string[];
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

/**
 * A journal placed relative to today, which is how every task fixture dates one.
 *
 * `cancellable` gives the journal the EVENT type so its `event_state` can later
 * be set to cancelled — the second of the two ways a task lapses.
 */
export interface RelativeJournalRequest {
  title: string;
  content?: string;
  exactTitle?: boolean;
  cancellable?: boolean;
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
  // Deleted before journals: a journal that anchors a task cannot be deleted
  // (ITER18-002 refuses it with a 409), so leaving tasks behind would leak
  // every journal a task fixture created.
  private createdTaskIds: string[] = [];
  private createdGearItemIds: string[] = [];
  private createdTemplateIds: string[] = [];
  private readonly createdCalendars: string[] = [];
  /** The calendar cancellable EVENT journals are filed in; created on demand. */
  private fixtureCalendarId: string | undefined;

  constructor(private readonly page: Page) {}

  /**
   * Generate a unique identifier for test data
   * Uses crypto.randomUUID() for guaranteed uniqueness even in parallel tests
   */
  private generateUniqueId(): string {
    return crypto.randomUUID().slice(0, 8);
  }

  /**
   * Delete a contact the test created some other way (e.g. through the UI)
   * during cleanup, as if this manager had created it.
   */
  trackContact(contactId: string): void {
    this.createdContactIds.push(contactId);
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
   * Add an email or phone to a contact, optionally already archived.
   *
   * Emails are unique across every contact, so callers pass a value made
   * unique per test.
   */
  async addContactMethod(
    contactId: string,
    method: {
      method_type: 'email' | 'phone';
      value: string;
      is_primary?: boolean;
      is_archived?: boolean;
    }
  ): Promise<void> {
    const response = await this.page.request.post(
      `/api/contacts/${contactId}/methods`,
      {
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify({
          data: {
            type: 'contact_methods',
            attributes: {
              is_primary: false,
              is_archived: false,
              ...method,
            },
          },
        }),
      }
    );
    if (!response.ok()) {
      throw new Error(
        `Failed to add contact method: ${response.status()} ${await response.text()}`
      );
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
   * The two journals every task needs, dated in **UTC**.
   *
   * A task is anchored to the journal it arose in and the journal it is due
   * in, and the due journal must be dated after today. The e2e user has no
   * configured timezone, so the backend resolves "today" against UTC — which
   * is why these offsets are applied to a UTC instant rather than to a local
   * wall-clock time.
   *
   * Returns `[creating, due]`.
   */
  async createTaskAnchorJournals(
    titlePrefix: string
  ): Promise<[TestJournal, TestJournal]> {
    const day = 24 * 60 * 60 * 1000;
    const now = Date.now();
    const range = (offsetDays: number) => {
      const start = new Date(now + offsetDays * day).toISOString();
      const end = new Date(
        now + offsetDays * day + 60 * 60 * 1000
      ).toISOString();
      return { start, end };
    };

    const creating = await this.createJournal({
      title: `${titlePrefix} created in`,
      content: 'Task anchor seeded for e2e testing',
      event_date_range: range(0),
    });
    const due = await this.createJournal({
      title: `${titlePrefix} due in`,
      content: 'Task anchor seeded for e2e testing',
      event_date_range: range(7),
    });

    return [creating, due];
  }

  /**
   * Link a contact to an existing task.
   *
   * A plain reference — no relationship type, role or attendance status — so
   * the body is a resource identifier and nothing else.
   */
  async linkTaskToContact(taskId: string, contactId: string): Promise<void> {
    const response = await this.page.request.post(
      `/api/tasks/${taskId}/relationships/contacts`,
      {
        headers: { 'Content-Type': 'application/json' },
        data: JSON.stringify({ data: { type: 'contacts', id: contactId } }),
      }
    );

    if (!response.ok()) {
      throw new Error(
        `Failed to link task ${taskId} to contact ${contactId}: ` +
          `${response.status()} ${await response.text()}`
      );
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
   * Create a journal dated `daysAhead` days from today, in UTC.
   *
   * The helper a task's **due** anchor comes from: a task's due journal must be
   * dated after today at the moment it is set, and the only way to satisfy that
   * deterministically is to say how far ahead in whole UTC days.
   *
   * Pass `cancellable` when the journal is going to be cancelled later.
   * Cancelling is an edit to an EVENT journal's `event_state`, so the journal
   * has to carry the EVENT type from the start — and EVENT type data requires a
   * calendar, which {@link ensureCalendar} supplies.
   */
  async createFutureJournal(
    options: RelativeJournalRequest & { daysAhead?: number }
  ): Promise<TestJournal> {
    const { daysAhead = 2, ...rest } = options;
    return this.createRelativeJournal({ ...rest, dayOffset: daysAhead });
  }

  /**
   * Create a journal dated `daysAgo` days before today, in UTC.
   *
   * Nothing can be made *due* in one — the service refuses a past anchor when it
   * is set — so this exists for the other side of the model: the journal a
   * commitment arose in, which has no date rule of its own.
   */
  async createPastJournal(
    options: RelativeJournalRequest & { daysAgo?: number }
  ): Promise<TestJournal> {
    const { daysAgo = 2, ...rest } = options;
    return this.createRelativeJournal({ ...rest, dayOffset: -daysAgo });
  }

  /**
   * Create a journal dated relative to today, in whole UTC days.
   *
   * `dayOffset` is signed, so this is the one builder behind
   * {@link createFutureJournal} and {@link createPastJournal}; `0` is today.
   */
  async createRelativeJournal(
    options: RelativeJournalRequest & { dayOffset: number }
  ): Promise<TestJournal> {
    const {
      title,
      content = 'Created by the journal task e2e fixtures.',
      dayOffset,
      cancellable = false,
      exactTitle,
    } = options;

    const eventType = cancellable
      ? {
          types: ['event'],
          type_data: {
            event: {
              calendar_id: await this.ensureCalendar(),
              is_all_day: false,
              sync_invitees: false,
            },
          },
        }
      : { types: ['note'] };

    return this.createJournal({
      title,
      ...(exactTitle === undefined ? {} : { exactTitle }),
      content,
      event_date_range: {
        start: utcDayOffset(dayOffset),
        end: utcDayOffset(dayOffset, 13),
      },
      ...eventType,
    });
  }

  /**
   * Cancel a journal, which lapses every not-done task due in it.
   *
   * Cancellation is not an endpoint of its own: it is `event_state` on an EVENT
   * journal's type data, so the journal must have been created with
   * `cancellable: true`.
   *
   * The response is **returned rather than asserted here**, because whether the
   * cancellation was accepted is part of what the lapsed specs are testing —
   * see {@link moveJournalToPast} for why that matters.
   */
  async cancelJournal(journalId: string): Promise<APIResponse> {
    console.debug(`🚫 [Data Manager] Cancelling journal ${journalId}`);

    return this.page.request.put(
      `/api/journals/${journalId}/types/EVENT/data`,
      {
        headers: { 'Content-Type': 'application/vnd.api+json' },
        data: JSON.stringify({
          data: {
            type: 'journal-type-data',
            attributes: { event_state: 'cancelled' },
          },
        }),
      }
    );
  }

  /**
   * Move a journal's event date range into the past.
   *
   * **This is half of the lapsed-task fixture recipe, and there is no other
   * way.** A task's due journal must be future-dated at the moment it is set,
   * and both write paths — create and retarget — enforce it, so no sequence of
   * task calls can produce a lapsed task. The journal has to move instead: the
   * journal update endpoint deliberately does not re-validate task invariants,
   * because a task whose due journal has drifted into the past is *lapsed*, not
   * invalid.
   *
   * The response is returned so the calling spec can **assert** that the update
   * succeeded. That assertion is the point: if journal update ever learned to
   * re-check task invariants, this recipe would stop producing lapsed tasks and
   * the specs built on it would quietly test nothing. Asserting the 2xx makes
   * that failure loud.
   */
  async moveJournalToPast(
    journalId: string,
    daysAgo: number
  ): Promise<APIResponse> {
    console.debug(
      `⏪ [Data Manager] Moving journal ${journalId} ${daysAgo} day(s) into the past`
    );

    return this.page.request.patch(`/api/journals/${journalId}`, {
      headers: { 'Content-Type': 'application/vnd.api+json' },
      data: JSON.stringify({
        data: {
          type: 'journals',
          id: journalId,
          attributes: {
            event_date_range: {
              start: utcDayOffset(-daysAgo),
              end: utcDayOffset(-daysAgo, 13),
            },
          },
        },
      }),
    });
  }

  /**
   * Delete every journal that has not already ended, so no future journal exists.
   *
   * The empty-picker spec needs the *absence* of future journals, which no
   * fixture can create by adding data — the e2e user is shared and a journal
   * another spec left behind would fill the picker this one asserts is empty.
   *
   * **This deletes journals it did not create, so it is destructive to the
   * shared account and safe only while the suite runs serially.** The filter is
   * `event_date_range.end >= today`, which is deliberately generous: it also
   * removes a journal that *started* weeks ago and merely runs past today,
   * because such a journal is still ahead of the picker's boundary in one
   * direction and would keep the window non-empty. `playwright.config.ts` pins
   * `workers: 1`; under parallel workers this would delete another test's live
   * fixtures, so call it only from a spec that can assume that.
   *
   * A journal anchoring a task refuses deletion with 409
   * `JOURNAL_HAS_ANCHORED_TASKS`, and the refusal names its blockers, so the
   * blocking tasks are deleted and the journal retried. That is the only route
   * available: tasks have no listing of their own by design, so the error body
   * is where their ids come from.
   */
  async clearFutureJournals(): Promise<void> {
    console.debug(
      `🧹 [Data Manager] Clearing journals dated today or later...`
    );

    const today = utcDayOffset(0).slice(0, 10);

    // Bounded by **progress**, not by a round count. A fixed number of rounds
    // silently caps how much this can clear — five pages of 100 is 500 journals,
    // and an account past that would be left holding future journals while the
    // caller was told the window was empty, which is the one thing an
    // empty-state fixture must never do. Looping while each round deletes
    // something has no cap and still cannot spin: a round that deletes nothing
    // while journals remain means something is refusing or recreating them, and
    // that is the error worth raising.
    for (;;) {
      const journals = await this.listJournalsFrom(today);
      if (journals.length === 0) {
        console.debug(`✅ [Data Manager] No future journals remain`);
        return;
      }

      let deleted = 0;
      for (const journal of journals) {
        await this.deleteJournalAndItsTasks(String(journal.id));
        deleted++;
      }

      if (deleted === 0) {
        throw new Error(
          `${journals.length} future journal(s) survived a full round of deletion; ` +
            'something is recreating them or refusing deletion for an unhandled reason'
        );
      }
    }
  }

  /**
   * Delete every journal whose date range touches `day` (a UTC `YYYY-MM-DD`),
   * together with any task anchored to it.
   *
   * For a test whose assertion *is* a day's journal count — today's AI summary
   * counts them — on an account where specs that create journals through the UI
   * leave today's behind: a full run holds several, and a test counting from an
   * assumed zero fails for a reason that has nothing to do with it.
   *
   * **Destructive to the shared account** in exactly the way
   * {@link clearFutureJournals} is, and safe for the same reason: `workers: 1`.
   * Bounded by progress: a journal still listed after this call already deleted
   * it means something is recreating it, and that is raised rather than looped.
   */
  async clearJournalsOn(day: string): Promise<void> {
    console.debug(`🧹 [Data Manager] Clearing journals on ${day}...`);
    const deleted = new Set<string>();

    for (;;) {
      const journals = await this.listJournalsOn(day);
      if (journals.length === 0) {
        return;
      }
      for (const journal of journals) {
        const id = String(journal.id);
        if (deleted.has(id)) {
          throw new Error(
            `Journal ${id} on ${day} survived its own deletion; something is recreating it`
          );
        }
        await this.deleteJournalAndItsTasks(id);
        deleted.add(id);
      }
    }
  }

  /** One page of the journals whose date range touches `day`. */
  private listJournalsOn(day: string): Promise<Array<{ id: string | number }>> {
    return this.listJournalsWhere(
      `start_date=${day}&end_date=${day}`,
      `on ${day}`
    );
  }

  /** One page of the journals whose date range has not ended before `from`. */
  private listJournalsFrom(
    from: string
  ): Promise<Array<{ id: string | number }>> {
    return this.listJournalsWhere(`start_date=${from}`, `from ${from}`);
  }

  /** One page of `/api/journals` under a date filter, raising when it fails. */
  private async listJournalsWhere(
    filter: string,
    described: string
  ): Promise<Array<{ id: string | number }>> {
    const response = await this.page.request.get(
      `/api/journals?${filter}&limit=100`,
      { headers: { Accept: 'application/vnd.api+json' } }
    );
    if (!response.ok()) {
      throw new Error(
        `Failed to list journals ${described}: ${response.status()} ${await response.text()}`
      );
    }
    return (await response.json()).data ?? [];
  }

  /**
   * Create a task against a journal.
   *
   * The creating journal is the journal it is created *from* and is never
   * chosen separately, which is why it is part of the route rather than the
   * body. The due journal must be dated after today; build it with
   * {@link createFutureJournal}, or take both anchors at once from
   * {@link createTaskAnchorJournals}.
   *
   * Created through the API rather than the UI so a spec that is *about* the
   * task — its history, or where it appears — does not depend on the creation
   * dialog to arrange it.
   */
  /**
   * Change a task's text through the API.
   *
   * A task write the test can place last in the event stream: its invalidation
   * of the day the task is due in follows every earlier one, so a test that
   * waits to see it knows nothing seeded before it is still on its way.
   */
  async updateTaskText(taskId: string, text: string): Promise<void> {
    const response = await this.page.request.patch(`/api/tasks/${taskId}`, {
      headers: { 'Content-Type': 'application/vnd.api+json' },
      data: JSON.stringify({
        data: { type: 'tasks', id: taskId, attributes: { text } },
      }),
    });
    if (!response.ok()) {
      throw new Error(
        `Failed to update task ${taskId}: ${response.status()} ${await response.text()}`
      );
    }
  }

  async createTask(taskData: TaskCreateRequest): Promise<TestTask> {
    console.debug(
      `📋 [Data Manager] Creating task "${taskData.text}" in journal ${taskData.creatingJournalId}`
    );

    const response = await this.page.request.post(
      `/api/journals/${taskData.creatingJournalId}/tasks`,
      {
        headers: { 'Content-Type': 'application/vnd.api+json' },
        data: JSON.stringify({
          data: {
            type: 'tasks',
            attributes: {
              text: taskData.text,
              due_journal_id: Number.parseInt(taskData.dueJournalId, 10),
              ...(taskData.contactIds
                ? {
                    contact_ids: taskData.contactIds.map(id =>
                      Number.parseInt(id, 10)
                    ),
                  }
                : {}),
            },
          },
        }),
      }
    );

    if (!response.ok()) {
      throw new Error(
        `Failed to create task: ${response.status()} ${await response.text()}`
      );
    }

    const resource = (await response.json()).data;
    // Tracked so cleanup can remove it *before* its journals — see
    // performCleanup, where the ordering is the whole point.
    this.createdTaskIds.push(String(resource.id));

    console.debug(`✅ [Data Manager] Created task ${resource.id}`);

    return {
      id: String(resource.id),
      text: resource.attributes.text,
      status: resource.attributes.status,
      creatingJournalId: String(resource.attributes.creating_journal_id),
      dueJournalId: String(resource.attributes.due_journal_id),
    };
  }

  /**
   * Link a task to a journal as an intermediate journal — a *mention*.
   *
   * The explicit half of the intermediate model: the automatic half is the
   * previous due journal a retarget leaves behind, and no fixture can ask for
   * that directly.
   */
  async attachTaskMention(taskId: string, journalId: string): Promise<void> {
    const response = await this.page.request.post(
      `/api/tasks/${taskId}/relationships/intermediate-journals`,
      {
        headers: { 'Content-Type': 'application/vnd.api+json' },
        data: JSON.stringify({
          data: { type: 'journals', id: String(journalId) },
        }),
      }
    );

    if (!response.ok()) {
      throw new Error(
        `Failed to attach journal ${journalId} to task ${taskId}: ` +
          `${response.status()} ${await response.text()}`
      );
    }

    console.debug(
      `🔗 [Data Manager] Attached journal ${journalId} to task ${taskId} as a mention`
    );
  }

  /** Delete a task, and stop tracking it for cleanup. */
  async deleteTask(taskId: string): Promise<void> {
    const response = await this.page.request.delete(`/api/tasks/${taskId}`);

    // A task the test itself deleted through the UI is already gone, and that
    // is a success for this helper's purpose rather than something to raise on.
    if (!response.ok() && response.status() !== 404) {
      throw new Error(
        `Failed to delete task ${taskId}: ${response.status()} ${await response.text()}`
      );
    }

    this.createdTaskIds = this.createdTaskIds.filter(id => id !== taskId);
    console.debug(`🗑️ [Data Manager] Deleted task ${taskId}`);
  }

  /**
   * Delete one journal, clearing the tasks anchored to it if it refuses.
   *
   * The 409's `meta.blocking_tasks` is the machine-readable half of the
   * delete-guard failure ITER18-002 ships, and it carries each blocker's
   * `task_id` — which is what makes this recoverable without a task listing.
   */
  private async deleteJournalAndItsTasks(journalId: string): Promise<void> {
    const first = await this.page.request.delete(`/api/journals/${journalId}`);
    // 404 is a journal the test already removed itself — the outcome this asks
    // for, reached by another route.
    if (first.ok() || first.status() === 404) return;

    if (first.status() !== 409) {
      throw new Error(
        `Failed to delete journal ${journalId}: ${first.status()} ${await first.text()}`
      );
    }

    const body = await first.json();
    const blockers = body.errors?.[0]?.meta?.blocking_tasks ?? [];
    console.debug(
      `🔗 [Data Manager] Journal ${journalId} anchors ${blockers.length} task(s); removing them first`
    );

    for (const blocker of blockers) {
      await this.deleteTask(String(blocker.task_id));
    }

    const retry = await this.page.request.delete(`/api/journals/${journalId}`);
    if (!retry.ok()) {
      throw new Error(
        `Journal ${journalId} still refused deletion after clearing its tasks: ` +
          `${retry.status()} ${await retry.text()}`
      );
    }
  }

  /**
   * The calendar EVENT journals are filed in, created once per manager.
   *
   * Every cancellable journal needs one and none of them care which, so a
   * second calendar per journal would be cleanup this manager has to do for no
   * test's benefit.
   */
  private async ensureCalendar(): Promise<string> {
    if (this.fixtureCalendarId) return this.fixtureCalendarId;

    const [calendar] = await this.createCalendars([
      { name: `TaskFixtures_${this.generateUniqueId()}`, color: '#3B82F6' },
    ]);
    this.fixtureCalendarId = calendar.id;
    return calendar.id;
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
   * Create a GEAR_USAGE journal recording the use of `gearItemIds`, in order.
   *
   * The checkout window resolves to the journal's event range, so a range
   * spanning "now" is a currently-checked-out item and a past range is not.
   */
  async createGearUsageJournal(options: {
    title: string;
    gearItemIds: string[];
    start: string;
    end: string;
  }): Promise<TestJournal> {
    return this.createJournal({
      title: options.title,
      content: 'Gear usage seeded for e2e testing',
      event_date_range: { start: options.start, end: options.end },
      types: ['gear_usage'],
      type_data: {
        gear_usage: {
          items: options.gearItemIds.map(gearItemId => ({
            gear_item_id: gearItemId,
          })),
        },
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
   * Clear all journals (for test setup).
   *
   * Pages until the listing comes back empty. It used to read one page at the
   * endpoint's default size and stop, so an account holding more than twenty
   * journals kept the rest while callers — who read this name as a guarantee —
   * went on to assert an empty list.
   *
   * **It raises rather than reporting a success it did not achieve.** Callers
   * like `emptyJournalsPage` build their whole assertion on this having worked,
   * so a listing that failed or a journal that would not go has to stop the
   * setup where it happened. A test that proceeds on leftovers fails later, on
   * an assertion that describes the symptom rather than the cause. In teardown
   * this is harmless: the `testCleanup` fixture runs each task in its own
   * try/catch, so the failure is logged rather than replacing the verdict.
   */
  async clearAllJournals(): Promise<void> {
    console.debug(`🧹 [Data Manager] Clearing all journals...`);

    // Bounded by progress rather than by a page count, for the reason
    // `clearFutureJournals` is: a fixed number of rounds is a silent cap on
    // how much this can actually clear.
    for (;;) {
      const response = await this.page.request.get('/api/journals?limit=100', {
        headers: { Accept: 'application/vnd.api+json' },
      });

      if (!response.ok()) {
        throw new Error(
          `Failed to list journals while clearing them: ` +
            `${response.status()} ${await response.text()}`
        );
      }

      const journals = (await response.json()).data || [];
      if (journals.length === 0) break;

      console.debug(
        `🧹 [Data Manager] Found ${journals.length} journals to delete`
      );

      // Delete each journal, tasks and all. A plain DELETE is refused with 409
      // for any journal anchoring a task, and this helper's callers read its
      // name as a guarantee: a journal left behind by a swallowed refusal is a
      // journal they will then assert is not there.
      const failures: string[] = [];
      for (const journal of journals) {
        try {
          await this.deleteJournalAndItsTasks(String(journal.id));
          console.debug(
            `🗑️ [Data Manager] Deleted existing journal ${journal.id}`
          );
        } catch (error) {
          failures.push(
            `${journal.id} (${error instanceof Error ? error.message : String(error)})`
          );
        }
      }

      // Every journal on the page refused deletion, so another pass would fetch
      // the same page and refuse it again. A partial failure is *not* fatal
      // here — the survivors come back on the next listing, and this is where
      // they are finally accounted for.
      if (failures.length === journals.length) {
        throw new Error(
          `Could not clear ${journals.length} journal(s): ${failures.join('; ')}`
        );
      }
    }

    console.debug(`✅ [Data Manager] All journals cleared`);
  }

  /**
   * Clean up all created test data
   */
  async cleanup(): Promise<void> {
    console.debug(
      `🧹 [Data Manager] Starting cleanup of ${this.createdContactIds.length} contacts, ${this.createdTagIds.length} contact tags, ${this.createdJournalTagIds.length} journal tags, ${this.createdJournalIds.length} journals, ${this.createdTaskIds.length} tasks, ${this.createdCalendars.length} calendars, ${this.createdGearItemIds.length} gear items, and ${this.createdTemplateIds.length} templates...`
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

  /**
   * Delete every journal this manager created, tasks and all.
   *
   * Failures are logged rather than raised, as everywhere else in cleanup: a
   * teardown that throws replaces the test's real verdict with its own.
   */
  private async cleanupJournals(): Promise<void> {
    await this.deleteInBatches(this.createdJournalIds, 'journal', async id => {
      await this.deleteJournalAndItsTasks(id);
      return true;
    });
  }

  private async cleanupSpecificItems(
    items: readonly string[],
    endpointPrefix: string,
    itemName: string
  ): Promise<void> {
    await this.deleteInBatches(items, itemName, async id => {
      const response = await this.page.request.delete(
        `${endpointPrefix}/${id}`
      );
      // 404 means already gone — that is the outcome cleanup wants.
      return response.ok() || response.status() === 404;
    });
  }

  /**
   * Delete items in concurrent batches, then retry any failures once,
   * sequentially and in order.
   *
   * The batches carry the speed: one HTTP round-trip per BATCH instead of per
   * item. The sequential retry pass carries the correctness: hierarchies
   * (parent/child tags, journals with children) can refuse a delete while a
   * sibling in the same batch still holds a reference, and in the shared
   * backend namespace a leaked item pollutes every test after this one — so
   * an ordering casualty gets a second, conflict-free attempt rather than a
   * log line.
   */
  private async deleteInBatches(
    items: readonly string[],
    itemName: string,
    deleteOne: (id: string) => Promise<boolean>
  ): Promise<void> {
    const batchSize = 10;
    const failed: string[] = [];

    for (let i = 0; i < items.length; i += batchSize) {
      const batch = items.slice(i, i + batchSize);
      await Promise.allSettled(
        batch.map(async itemId => {
          try {
            if (await deleteOne(itemId)) {
              console.debug(`🗑️ [Data Manager] Deleted ${itemName} ${itemId}`);
            } else {
              failed.push(itemId);
            }
          } catch {
            failed.push(itemId);
          }
        })
      );
    }

    for (const itemId of failed) {
      try {
        if (await deleteOne(itemId)) {
          console.debug(
            `🗑️ [Data Manager] Deleted ${itemName} ${itemId} on retry`
          );
        } else {
          console.debug(
            `⚠️ [Data Manager] Failed to delete ${itemName} ${itemId} after retry`
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

    // Tasks go **before** journals, and the order is load-bearing rather than
    // tidy. Both anchors are ON DELETE RESTRICT, so a journal that is the
    // creating or due journal of any task refuses deletion with 409
    // JOURNAL_HAS_ANCHORED_TASKS whatever the task's status — and leaving the
    // tasks in place would leak this test's journals into every test after it,
    // and into the pickers and listings they assert on.
    await this.cleanupSpecificItems(this.createdTaskIds, '/api/tasks', 'task');

    // Task-aware, because the pass above only knows about tasks this manager
    // created through the API. A task the *test* created through the UI is
    // anchored to these journals just as firmly, and would refuse their
    // deletion the same way.
    await this.cleanupJournals();
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
    this.createdTaskIds = [];
    this.createdGearItemIds = [];
    this.createdTemplateIds = [];
    // The cached calendar was deleted with the rest; keeping its id would hand
    // the next cancellable journal a calendar that no longer exists.
    this.fixtureCalendarId = undefined;
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
    const randomStr = crypto.randomUUID().slice(0, 8);
    return Array.from({ length: count }, (_, index) =>
      this.create({
        name: `${prefix}-${index + 1}-${Date.now()}-${randomStr}`,
      })
    );
  }

  static createHierarchy(): TagCreateRequest[] {
    const timestamp = Date.now();
    const randomStr = crypto.randomUUID().slice(0, 8);
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
