/**
 * Contact fixtures for Playwright e2e tests.
 *
 * Provides mock contact data and API responses for testing
 * the contacts functionality without requiring a real backend.
 */

import { Page, Route } from '@playwright/test';

// Mock contact data for testing
export const MOCK_CONTACTS = [
  {
    id: '1',
    type: 'contact',
    attributes: {
      first_name: 'John',
      last_name: 'Doe',
      middle_name: null,
      nickname: null,
      contact_methods: [
        {
          id: '1',
          type: 'contact_method',
          attributes: {
            method_type: 'email',
            value: 'john@example.com',
            is_primary: true,
            label: 'Personal',
          },
        },
        {
          id: '2',
          type: 'contact_method',
          attributes: {
            method_type: 'phone',
            value: '+1234567890',
            is_primary: true,
            label: 'Mobile',
          },
        },
      ],
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    },
    relationships: {
      tags: {
        data: [],
      },
    },
  },
  {
    id: '2',
    type: 'contact',
    attributes: {
      first_name: 'Jane',
      last_name: 'Smith',
      middle_name: 'Marie',
      nickname: 'Janie',
      contact_methods: [
        {
          id: '3',
          type: 'contact_method',
          attributes: {
            method_type: 'email',
            value: 'jane@example.com',
            is_primary: true,
            label: 'Work',
          },
        },
      ],
      created_at: '2024-01-02T00:00:00Z',
      updated_at: '2024-01-02T00:00:00Z',
    },
    relationships: {
      tags: {
        data: [
          {
            id: '1',
            type: 'tag',
            attributes: {
              name: 'Work',
              color: '#3b82f6',
            },
          },
        ],
      },
    },
  },
] as const;

// API endpoint patterns for mocking
export const CONTACTS_API_PATTERNS = {
  CONTACTS: '**/api/contacts',
  CONTACTS_SEARCH: '**/api/contacts/search',
  CONTACT_BY_ID: '**/api/contacts/*',
} as const;

// Mock API responses
export const MOCK_CONTACTS_RESPONSES = {
  contactsList: () => ({
    data: MOCK_CONTACTS,
    meta: {
      total: MOCK_CONTACTS.length,
      page: 1,
      per_page: 20,
      total_pages: 1,
    },
  }),

  contactsEmpty: () => ({
    data: [],
    meta: {
      total: 0,
      page: 1,
      per_page: 20,
      total_pages: 0,
    },
  }),

  contactsSearch: (query: string) => {
    const filtered = MOCK_CONTACTS.filter(contact =>
      contact.attributes.first_name.toLowerCase().includes(query.toLowerCase()) ||
      contact.attributes.last_name?.toLowerCase().includes(query.toLowerCase()) ||
      contact.attributes.contact_methods.some(method =>
        method.attributes.value.toLowerCase().includes(query.toLowerCase())
      )
    );

    return {
      data: filtered.map(contact => ({
        ...contact,
        meta: {
          highlighted: {
            first_name: contact.attributes.first_name.replace(
              new RegExp(query, 'gi'),
              `<mark>$&</mark>`
            ),
            last_name: contact.attributes.last_name?.replace(
              new RegExp(query, 'gi'),
              `<mark>$&</mark>`
            ),
          },
        },
      })),
      meta: {
        total: filtered.length,
        page: 1,
        per_page: 20,
        total_pages: Math.ceil(filtered.length / 20),
        processing_time_ms: 15,
      },
    };
  },

  contactById: (id: string) => {
    const contact = MOCK_CONTACTS.find(c => c.id === id);
    return contact ? { data: contact } : null;
  },

  contactsError: () => ({
    errors: [
      {
        code: 'INTERNAL_ERROR',
        detail: 'Failed to load contacts',
        status: '500',
      },
    ],
  }),
} as const;

/**
 * Mock contacts API responses for testing.
 */
export class ContactsFixtures {
  constructor(private readonly page: Page) {}

  /**
   * Mock contacts list endpoint with sample data.
   */
  async mockContactsList(): Promise<void> {
    await this.page.route(CONTACTS_API_PATTERNS.CONTACTS, async (route: Route) => {
      const url = new URL(route.request().url());
      const searchParams = url.searchParams;
      
      // Check if this is a search request
      if (searchParams.has('q')) {
        const query = searchParams.get('q') || '';
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_CONTACTS_RESPONSES.contactsSearch(query)),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_CONTACTS_RESPONSES.contactsList()),
        });
      }
    });
  }

  /**
   * Mock contacts search endpoint.
   */
  async mockContactsSearch(): Promise<void> {
    await this.page.route(CONTACTS_API_PATTERNS.CONTACTS_SEARCH, async (route: Route) => {
      const url = new URL(route.request().url());
      const query = url.searchParams.get('q') || '';
      
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_CONTACTS_RESPONSES.contactsSearch(query)),
      });
    });
  }

  /**
   * Mock empty contacts list.
   */
  async mockContactsEmpty(): Promise<void> {
    await this.page.route(CONTACTS_API_PATTERNS.CONTACTS, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_CONTACTS_RESPONSES.contactsEmpty()),
      });
    });
  }

  /**
   * Mock contacts API error.
   */
  async mockContactsError(): Promise<void> {
    await this.page.route(CONTACTS_API_PATTERNS.CONTACTS, async (route: Route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_CONTACTS_RESPONSES.contactsError()),
      });
    });
  }

  /**
   * Mock contact by ID endpoint.
   */
  async mockContactById(id: string): Promise<void> {
    await this.page.route(`**/api/contacts/${id}`, async (route: Route) => {
      const response = MOCK_CONTACTS_RESPONSES.contactById(id);
      if (response) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(response),
        });
      } else {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({
            errors: [
              {
                code: 'NOT_FOUND',
                detail: 'Contact not found',
                status: '404',
              },
            ],
          }),
        });
      }
    });
  }

  /**
   * Clear all contacts-related route mocks.
   */
  async clearMocks(): Promise<void> {
    await this.page.unroute(CONTACTS_API_PATTERNS.CONTACTS);
    await this.page.unroute(CONTACTS_API_PATTERNS.CONTACTS_SEARCH);
    await this.page.unroute(CONTACTS_API_PATTERNS.CONTACT_BY_ID);
  }
}

/**
 * Create contacts fixtures for a page.
 */
export function createContactsFixtures(page: Page): ContactsFixtures {
  return new ContactsFixtures(page);
}
