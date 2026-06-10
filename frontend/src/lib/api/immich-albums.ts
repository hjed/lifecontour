/**
 * Immich album-creation API client (ITER11-006 Phase 2).
 *
 * Wires the journal album-creation UI to the Phase 1 backend endpoints:
 * `POST /api/integrations/immich/search-photos` and
 * `POST /api/integrations/immich/create-album`. Thumbnails are backend proxy
 * URLs so the browser never sees the Immich server URL or API key.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { JsonApiErrorResponse } from '@/types/api';
import { externalLinkKeys } from './external-links';
import { journalKeys } from './journals';

const SEARCH_PHOTOS_ENDPOINT = '/api/integrations/immich/search-photos';
const CREATE_ALBUM_ENDPOINT = '/api/integrations/immich/create-album';

/** A candidate Immich photo, flattened from the JSON:API search response. */
export interface ImmichPhoto {
  readonly id: string;
  readonly thumbnailUrl: string;
  readonly originalFileName: string;
  readonly takenAt: string | null;
}

/** Raw JSON:API resource returned by the search endpoint. */
interface ImmichPhotoResource {
  id: string;
  type: string;
  attributes: {
    thumbnailUrl: string;
    originalFileName: string;
    takenAt: string | null;
  };
}

interface ImmichSearchPhotosApiResponse {
  data: ImmichPhotoResource[];
  meta: { count: number };
}

/** Caller-facing request shape for creating an album. */
export interface CreateImmichAlbumRequest {
  readonly journalId: string;
  readonly assetIds: string[];
  readonly createSharedLink: boolean;
}

export interface ImmichCreateAlbumResponse {
  data: {
    id: string;
    type: string;
    attributes: {
      journalId: number;
      assetCount: number;
      sharedLinkUrl: string | null;
    };
  };
}

/**
 * Convert a journal id (a numeric string in this app) to the integer the
 * backend expects, failing loudly rather than silently sending `null` (which
 * `JSON.stringify(NaN)` would produce) and causing an opaque server error.
 */
function toBackendJournalId(journalId: string): number {
  const id = Number(journalId);
  if (!Number.isInteger(id)) {
    throw new Error(`Invalid journal id: ${journalId}`);
  }
  return id;
}

/** Extract the JSON:API `errors[0].detail` message, or a sensible fallback. */
async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorData: JsonApiErrorResponse = await response.json();
      if (
        Array.isArray(errorData.errors) &&
        errorData.errors.length > 0 &&
        typeof errorData.errors[0].detail === 'string'
      ) {
        message = errorData.errors[0].detail;
      }
    } catch {
      // Non-JSON body (e.g. proxy error page) — keep the status-based message.
    }
    throw new Error(message);
  }
  return response.json();
}

/**
 * Search Immich for photos within a journal's date range. Returns the photos
 * flattened for direct use in the selection grid.
 */
export async function searchImmichPhotos(
  journalId: string
): Promise<ImmichPhoto[]> {
  const response = await fetch(SEARCH_PHOTOS_ENDPOINT, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ journal_id: toBackendJournalId(journalId) }),
  });

  const body = await handleResponse<ImmichSearchPhotosApiResponse>(response);
  return body.data.map(resource => ({
    id: resource.id,
    thumbnailUrl: resource.attributes.thumbnailUrl,
    originalFileName: resource.attributes.originalFileName,
    takenAt: resource.attributes.takenAt,
  }));
}

/** Create an Immich album from the selected photos and link it to the journal. */
export async function createImmichAlbum(
  request: CreateImmichAlbumRequest
): Promise<ImmichCreateAlbumResponse> {
  const response = await fetch(CREATE_ALBUM_ENDPOINT, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      journal_id: toBackendJournalId(request.journalId),
      asset_ids: request.assetIds,
      create_shared_link: request.createSharedLink,
    }),
  });

  return handleResponse<ImmichCreateAlbumResponse>(response);
}

/**
 * On-demand photo search triggered by the "Create Album" button. Modelled as a
 * mutation so the button gets a loading state and the dialog opens with the
 * result.
 */
export function useImmichPhotoSearch() {
  return useMutation({
    mutationFn: (journalId: string) => searchImmichPhotos(journalId),
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

/**
 * Create an album, then refresh the journal detail and its external links so
 * the album banner and Immich links appear without a manual reload.
 */
export function useCreateImmichAlbum() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: CreateImmichAlbumRequest) =>
      createImmichAlbum(request),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: journalKeys.detail(variables.journalId),
      });
      queryClient.invalidateQueries({
        queryKey: externalLinkKeys.journal(variables.journalId),
      });
      toast.success('Album created successfully');
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}
