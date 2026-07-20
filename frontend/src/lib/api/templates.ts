import { API_ENDPOINTS } from '../constants';
import {
  ActivityTemplateCreateRequest,
  ActivityTemplateListResponse,
  ActivityTemplateResponse,
  ActivityTemplateType,
  ActivityTemplateUpdateRequest,
} from '@/types/journals';

/**
 * Get a list of activity templates, optionally filtered by type.
 */
export async function getTemplates(
  templateType?: ActivityTemplateType,
  name?: string
): Promise<ActivityTemplateListResponse> {
  const query = new URLSearchParams();
  if (templateType) query.append('template_type', templateType);
  if (name) query.append('name', name);

  const queryString = query.toString() ? `?${query.toString()}` : '';
  const response = await fetch(
    `${API_ENDPOINTS.TEMPLATES.BASE}${queryString}`,
    {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );

  if (!response.ok) {
    throw new Error('Failed to fetch activity templates');
  }

  return response.json();
}

/**
 * Get a specific activity template by ID.
 */
export async function getTemplate(
  id: string
): Promise<ActivityTemplateResponse> {
  const response = await fetch(API_ENDPOINTS.TEMPLATES.BY_ID(id), {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error('Failed to fetch activity template');
  }

  return response.json();
}

/**
 * Create a new activity template.
 */
export async function createTemplate(
  request: ActivityTemplateCreateRequest
): Promise<ActivityTemplateResponse> {
  const response = await fetch(API_ENDPOINTS.TEMPLATES.BASE, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error('Failed to create activity template');
  }

  return response.json();
}

/**
 * Update an existing activity template. The request body's data.id must match
 * the id in the URL or the backend rejects the request with a 400.
 */
export async function updateTemplate(
  id: string,
  request: ActivityTemplateUpdateRequest
): Promise<ActivityTemplateResponse> {
  const response = await fetch(API_ENDPOINTS.TEMPLATES.BY_ID(id), {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error('Failed to update activity template');
  }

  return response.json();
}

/**
 * Delete an activity template.
 */
export async function deleteTemplate(id: string): Promise<void> {
  const response = await fetch(API_ENDPOINTS.TEMPLATES.BY_ID(id), {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error('Failed to delete activity template');
  }
}
