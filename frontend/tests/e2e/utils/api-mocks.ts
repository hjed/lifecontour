/**
 * API mocking utilities for Playwright tests.
 * 
 * Provides consistent API responses for testing without relying on backend state.
 */

import { Page, Route } from '@playwright/test';
import { testContacts, testUser } from '../fixtures/test-data';

/**
 * Mock authentication endpoints
 */
export async function mockAuthEndpoints(page: Page) {
  // Mock auth providers endpoint
  await page.route('**/api/auth/providers', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          providers: [
            {
              name: 'github',
              display_name: 'GitHub',
              icon_url: null
            },
            {
              name: 'microsoft',
              display_name: 'Microsoft',
              icon_url: null
            }
          ]
        }
      })
    });
  });

  // Mock auth status endpoint
  await page.route('**/api/auth/status', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        authenticated: true,
        user: testUser
      })
    });
  });

  // Mock logout endpoint
  await page.route('**/api/auth/logout', async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        message: 'Logged out successfully'
      })
    });
  });
}

/**
 * Mock contact endpoints
 */
export async function mockContactEndpoints(page: Page) {
  // Mock contacts list endpoint
  await page.route('**/api/contacts**', async (route: Route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();

    if (method === 'GET') {
      const page = parseInt(url.searchParams.get('page') || '1');
      const limit = parseInt(url.searchParams.get('limit') || '20');
      const offset = (page - 1) * limit;
      
      const paginatedContacts = testContacts.slice(offset, offset + limit);
      
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: paginatedContacts.map(contact => ({
            type: 'contact',
            id: contact.id?.toString(),
            attributes: {
              first_name: contact.firstName,
              last_name: contact.lastName,
              email: contact.email,
              phone: contact.phone,
              company: contact.company,
              notes: contact.notes,
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z'
            },
            relationships: {
              tags: {
                data: contact.tags?.map(tag => ({
                  type: 'tag',
                  id: tag
                })) || []
              }
            }
          })),
          meta: {
            total: testContacts.length,
            page,
            limit,
            total_pages: Math.ceil(testContacts.length / limit)
          },
          links: {
            self: `/api/contacts?page=${page}&limit=${limit}`,
            first: `/api/contacts?page=1&limit=${limit}`,
            last: `/api/contacts?page=${Math.ceil(testContacts.length / limit)}&limit=${limit}`
          }
        })
      });
    } else if (method === 'POST') {
      // Mock contact creation
      const requestBody = await route.request().postDataJSON();
      const newContact = {
        type: 'contact',
        id: '999',
        attributes: {
          ...requestBody.data.attributes,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString()
        }
      };

      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          data: newContact
        })
      });
    }
  });

  // Mock individual contact endpoint
  await page.route('**/api/contacts/*', async (route: Route) => {
    const method = route.request().method();
    const contactId = route.request().url().split('/').pop();
    
    if (method === 'GET') {
      const contact = testContacts.find(c => c.id?.toString() === contactId);
      
      if (contact) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            data: {
              type: 'contact',
              id: contact.id?.toString(),
              attributes: {
                first_name: contact.firstName,
                last_name: contact.lastName,
                email: contact.email,
                phone: contact.phone,
                company: contact.company,
                notes: contact.notes,
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z'
              }
            }
          })
        });
      } else {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({
            errors: [{
              status: '404',
              title: 'Contact not found',
              detail: `Contact with ID ${contactId} not found`
            }]
          })
        });
      }
    } else if (method === 'PUT') {
      // Mock contact update
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            type: 'contact',
            id: contactId,
            attributes: {
              ...(await route.request().postDataJSON()).data.attributes,
              updated_at: new Date().toISOString()
            }
          }
        })
      });
    } else if (method === 'DELETE') {
      // Mock contact deletion
      await route.fulfill({
        status: 204
      });
    }
  });
}

/**
 * Mock search endpoints
 */
export async function mockSearchEndpoints(page: Page) {
  // Mock contact search endpoint
  await page.route('**/api/search/contacts**', async (route: Route) => {
    const url = new URL(route.request().url());
    const query = url.searchParams.get('q') || '';
    
    const filteredContacts = testContacts.filter(contact => 
      contact.firstName.toLowerCase().includes(query.toLowerCase()) ||
      contact.lastName.toLowerCase().includes(query.toLowerCase()) ||
      contact.email?.toLowerCase().includes(query.toLowerCase()) ||
      contact.company?.toLowerCase().includes(query.toLowerCase()) ||
      contact.tags?.some(tag => tag.toLowerCase().includes(query.toLowerCase()))
    );

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        hits: filteredContacts.map(contact => ({
          id: contact.id?.toString(),
          first_name: contact.firstName,
          last_name: contact.lastName,
          email: contact.email,
          company: contact.company,
          _formatted: {
            first_name: contact.firstName,
            last_name: contact.lastName,
            email: contact.email,
            company: contact.company
          }
        })),
        query,
        limit: 20,
        offset: 0,
        estimatedTotalHits: filteredContacts.length,
        processingTimeMs: 1
      })
    });
  });

  // Mock global search endpoint
  await page.route('**/api/search/global**', async (route: Route) => {
    const url = new URL(route.request().url());
    const query = url.searchParams.get('q') || '';
    
    const filteredContacts = testContacts.filter(contact => 
      contact.firstName.toLowerCase().includes(query.toLowerCase()) ||
      contact.lastName.toLowerCase().includes(query.toLowerCase())
    );

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contacts: {
          hits: filteredContacts.slice(0, 5),
          total: filteredContacts.length
        },
        journal: {
          hits: [],
          total: 0
        },
        calendar: {
          hits: [],
          total: 0
        }
      })
    });
  });
}

/**
 * Set up all API mocks for a page
 */
export async function setupApiMocks(page: Page) {
  await mockAuthEndpoints(page);
  await mockContactEndpoints(page);
  await mockSearchEndpoints(page);
}
