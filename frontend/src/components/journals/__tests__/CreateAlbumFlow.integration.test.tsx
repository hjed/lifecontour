/**
 * @jest-environment jsdom
 *
 * Integration test for the album-creation flow: real API client + real React
 * Query hooks wired together, with only the HTTP boundary (`global.fetch`)
 * mocked. Exercises button visibility → search → dialog → deselect → confirm,
 * and asserts the create-album request carries the reduced selection and that
 * the journal detail + external-links caches are invalidated so the banner and
 * links refresh.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CreateAlbumButton } from '../CreateAlbumButton';
import { JournalType, type Journal } from '@/types/journals';

jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

const JOURNAL: Journal = {
  id: '42',
  title: 'Trip to the coast',
  content: '',
  event_date_range: {
    start: '2024-01-15T00:00:00Z',
    end: '2024-01-16T00:00:00Z',
  },
  types: [JournalType.NOTE],
  contacts: [],
  tags: [],
  children: [],
} as Journal;

function json(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: async () => body });
}

function setupFetch() {
  const fetchMock = jest.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();

    if (url.endsWith('/api/integrations')) {
      return json({
        data: [
          {
            id: 'immich',
            type: 'integration',
            attributes: { status: 'connected' },
          },
        ],
      });
    }
    if (url.endsWith('/api/integrations/immich/search-photos')) {
      return json({
        data: [
          {
            id: 'asset-1',
            type: 'immich-photo',
            attributes: {
              thumbnailUrl: '/thumb/asset-1',
              originalFileName: 'one.jpg',
              takenAt: '2024-01-15T10:00:00Z',
            },
          },
          {
            id: 'asset-2',
            type: 'immich-photo',
            attributes: {
              thumbnailUrl: '/thumb/asset-2',
              originalFileName: 'two.jpg',
              takenAt: '2024-01-15T11:00:00Z',
            },
          },
        ],
        meta: { count: 2 },
      });
    }
    if (url.endsWith('/api/integrations/immich/create-album')) {
      return json({
        data: {
          id: 'album-1',
          type: 'immich-album',
          attributes: {
            journalId: 42,
            assetCount: 1,
            sharedLinkUrl: 'https://immich.example/share/abc',
          },
        },
      });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function getBody(fetchMock: jest.Mock, urlSuffix: string) {
  const call = fetchMock.mock.calls.find(([input]) =>
    (typeof input === 'string' ? input : String(input)).endsWith(urlSuffix)
  );
  return JSON.parse((call?.[1] as RequestInit).body as string);
}

describe('Album creation flow (integration)', () => {
  afterEach(() => {
    jest.resetAllMocks();
  });

  it('searches, lets the user deselect, then creates the album and refreshes caches', async () => {
    const fetchMock = setupFetch();
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries');
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <CreateAlbumButton journal={JOURNAL} />
      </QueryClientProvider>
    );

    // Button appears once the integrations query resolves "connected".
    const button = await screen.findByTestId('create-album-button');

    // Click → search → dialog opens with both photos selected.
    await user.click(button);
    await screen.findByTestId('create-album-dialog');
    expect(screen.getByTestId('photo-checkbox-asset-1')).toBeChecked();
    expect(screen.getByTestId('photo-checkbox-asset-2')).toBeChecked();

    // Deselect one photo, then confirm.
    await user.click(screen.getByTestId('photo-checkbox-asset-2'));
    await user.click(screen.getByTestId('create-album-confirm'));

    // create-album called with only the remaining asset id.
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith('/api/integrations/immich/create-album')
        )
      ).toBe(true);
    });
    const body = getBody(fetchMock, '/api/integrations/immich/create-album');
    expect(body).toEqual({
      journal_id: 42,
      asset_ids: ['asset-1'],
      create_shared_link: false,
    });

    // Journal detail + external-links caches invalidated so banner/links refresh.
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['journals', 'detail', '42'],
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['journals', '42', 'external-links'],
      });
    });
  });
});
