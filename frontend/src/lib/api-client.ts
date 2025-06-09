/**
 * API client for communicating with the FastAPI backend.
 *
 * Handles authentication, error handling, and JSON API format.
 */

import { API_ENDPOINTS, HTTP_HEADERS } from './constants';

export interface ApiError {
  status: string;
  title: string;
  detail: string;
}

export interface ApiResponse<T> {
  data?: T;
  errors?: ApiError[];
  meta?: Record<string, unknown>;
  links?: Record<string, string>;
}

export interface Contact {
  id: string;
  type: 'contact';
  attributes: {
    first_name: string;
    last_name: string;
    email?: string;
    phone?: string;
    company?: string;
    notes?: string;
    created_at: string;
    updated_at: string;
  };
  relationships?: {
    tags?: {
      data: Array<{ type: 'tag'; id: string }>;
    };
  };
}

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  provider: string;
}

export interface AuthStatus {
  authenticated: boolean;
  user?: AuthUser;
}

export interface SearchResult {
  hits: Array<{
    id: string;
    first_name: string;
    last_name: string;
    email?: string;
    company?: string;
    _formatted?: Record<string, string>;
  }>;
  query: string;
  limit: number;
  offset: number;
  estimatedTotalHits: number;
  processingTimeMs: number;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    // Use relative URLs in browser environment (including tests)
    // Use absolute URL for server-side rendering
    if (typeof window !== 'undefined') {
      this.baseUrl = baseUrl || '';
    } else {
      this.baseUrl = baseUrl || 'http://localhost:8000';
    }
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    const url = `${this.baseUrl}${endpoint}`;

    const defaultHeaders = {
      [HTTP_HEADERS.CONTENT_TYPE]: HTTP_HEADERS.APPLICATION_JSON,
    };

    const config: RequestInit = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
      credentials: 'include', // Include cookies for session management
    };

    try {
      const response = await fetch(url, config);

      if (!response.ok) {
        // Handle HTTP errors
        const errorData = await response.json().catch(() => ({
          errors: [
            {
              status: response.status.toString(),
              title: response.statusText,
              detail: `HTTP ${response.status} error`,
            },
          ],
        }));

        return errorData;
      }

      // Handle successful responses
      if (response.status === 204) {
        // No content response
        return { data: undefined as T };
      }

      const data = await response.json();
      return data;
    } catch (error) {
      // Handle network errors
      return {
        errors: [
          {
            status: '0',
            title: 'Network Error',
            detail:
              error instanceof Error ? error.message : 'Unknown network error',
          },
        ],
      };
    }
  }

  // Authentication methods
  async getAuthStatus(): Promise<ApiResponse<AuthStatus>> {
    return this.request<AuthStatus>(API_ENDPOINTS.AUTH.SESSION);
  }

  async getAuthProviders(): Promise<
    ApiResponse<{
      providers: Array<{
        name: string;
        display_name: string;
        icon_url?: string;
      }>;
    }>
  > {
    return this.request('/api/auth/providers');
  }

  async logout(): Promise<ApiResponse<{ message: string }>> {
    return this.request(API_ENDPOINTS.AUTH.LOGOUT, {
      method: 'POST',
    });
  }

  // Contact methods
  async getContacts(
    page: number = 1,
    limit: number = 20,
    search?: string
  ): Promise<ApiResponse<Contact[]>> {
    const params = new URLSearchParams({
      page: page.toString(),
      limit: limit.toString(),
    });

    if (search) {
      params.append('search', search);
    }

    return this.request<Contact[]>(`${API_ENDPOINTS.CONTACTS.BASE}?${params}`);
  }

  async getContact(id: string): Promise<ApiResponse<Contact>> {
    return this.request<Contact>(API_ENDPOINTS.CONTACTS.BY_ID(id));
  }

  async createContact(
    contactData: Partial<Contact['attributes']>
  ): Promise<ApiResponse<Contact>> {
    return this.request<Contact>(API_ENDPOINTS.CONTACTS.BASE, {
      method: 'POST',
      body: JSON.stringify({
        data: {
          type: 'contact',
          attributes: contactData,
        },
      }),
    });
  }

  async updateContact(
    id: string,
    contactData: Partial<Contact['attributes']>
  ): Promise<ApiResponse<Contact>> {
    return this.request<Contact>(API_ENDPOINTS.CONTACTS.BY_ID(id), {
      method: 'PUT',
      body: JSON.stringify({
        data: {
          type: 'contact',
          attributes: contactData,
        },
      }),
    });
  }

  async deleteContact(id: string): Promise<ApiResponse<void>> {
    return this.request<void>(API_ENDPOINTS.CONTACTS.BY_ID(id), {
      method: 'DELETE',
    });
  }

  // Search methods
  async searchContacts(
    query: string,
    limit: number = 20,
    offset: number = 0
  ): Promise<ApiResponse<SearchResult>> {
    const params = new URLSearchParams({
      q: query,
      limit: limit.toString(),
      offset: offset.toString(),
    });

    return this.request<SearchResult>(
      `${API_ENDPOINTS.SEARCH.CONTACTS}?${params}`
    );
  }

  async globalSearch(
    query: string,
    entityTypes?: string[]
  ): Promise<
    ApiResponse<{
      contacts: { hits: unknown[]; total: number };
      journal: { hits: unknown[]; total: number };
      calendar: { hits: unknown[]; total: number };
    }>
  > {
    const params = new URLSearchParams({ q: query });

    if (entityTypes) {
      params.append('entity_types', entityTypes.join(','));
    }

    return this.request(`${API_ENDPOINTS.SEARCH.GLOBAL}?${params}`);
  }

  async getSearchSuggestions(
    query: string
  ): Promise<ApiResponse<{ suggestions: string[] }>> {
    const params = new URLSearchParams({ q: query });
    return this.request(`${API_ENDPOINTS.SEARCH.SUGGESTIONS}?${params}`);
  }

  // Health check
  async getHealth(): Promise<
    ApiResponse<{
      status: string;
      timestamp: string;
      version: string;
      uptime: string;
    }>
  > {
    return this.request('/api/health');
  }
}

// Export singleton instance
export const apiClient = new ApiClient();
export default apiClient;
