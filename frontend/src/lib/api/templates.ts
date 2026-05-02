import { API_ENDPOINTS } from '../constants';
import {
  ActivityTemplateCreateRequest,
  ActivityTemplateListResponse,
  ActivityTemplateResponse,
  ActivityTemplateType,
} from '@/types/journals';

/**
 * Get a list of activity templates, optionally filtered by type.
 */
export async function getTemplates(
  templateType?: ActivityTemplateType,
  name?: string
): Promise<ActivityTemplateListResponse> {
  const url = new URL(API_ENDPOINTS.TEMPLATES.BASE, window.location.origin);
  if (templateType) {
    url.searchParams.append('template_type', templateType);
  }
  if (name) {
    url.searchParams.append('name', name);
  }

  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  });

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
