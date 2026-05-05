/**
 * Gear Items API client.
 *
 * Provides typed functions for communicating with the
 * gear items endpoints using standard fetch with auth.
 */

import type {
  GearItem,
  GearItemListResponse,
  GearItemResponse,
  GearItemCreateRequest,
  GearItemUpdateRequest,
} from '@/types/gearItems';

/**
 * Get all gear items, optionally filtered by search term.
 */
export async function getGearItems(search?: string): Promise<GearItem[]> {
  const url = new URL('/api/gear-items', window.location.origin);
  if (search) {
    url.searchParams.set('name', search);
  }

  const response = await fetch(url.toString(), { credentials: 'include' });

  if (!response.ok) {
    throw new Error('Failed to fetch gear items');
  }

  const result = (await response.json()) as GearItemListResponse;
  return result.data.map(item => ({
    id: item.id,
    ...item.attributes,
  }));
}

/**
 * Get a specific gear item by ID.
 */
export async function getGearItem(id: string): Promise<GearItem> {
  const response = await fetch(`/api/gear-items/${id}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(`Gear item with ID ${id} not found`);
    }
    throw new Error('Failed to fetch gear item');
  }

  const result = (await response.json()) as GearItemResponse;
  return {
    id: result.data.id,
    ...result.data.attributes,
  };
}

/**
 * Create a new gear item.
 */
export async function createGearItem(
  request: GearItemCreateRequest
): Promise<GearItem> {
  const response = await fetch('/api/gear-items', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error('Failed to create gear item');
  }

  const result = (await response.json()) as GearItemResponse;
  return {
    id: result.data.id,
    ...result.data.attributes,
  };
}

/**
 * Update an existing gear item.
 */
export async function updateGearItem(
  id: string,
  request: GearItemUpdateRequest
): Promise<GearItem> {
  const response = await fetch(`/api/gear-items/${id}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error('Failed to update gear item');
  }

  const result = (await response.json()) as GearItemResponse;
  return {
    id: result.data.id,
    ...result.data.attributes,
  };
}

/**
 * Delete a gear item.
 */
export async function deleteGearItem(id: string): Promise<void> {
  const response = await fetch(`/api/gear-items/${id}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error('Failed to delete gear item');
  }
}
