/**
 * @jest-environment jsdom
 */

import { createImmichAlbum, searchImmichPhotos } from '../immich-albums';

describe('immich-albums API client', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  describe('searchImmichPhotos', () => {
    it('POSTs the journal id and flattens the JSON:API response', async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: [
            {
              id: 'asset-1',
              type: 'immich-photo',
              attributes: {
                thumbnailUrl:
                  '/api/integrations/immich/assets/asset-1/thumbnail',
                originalFileName: 'beach.jpg',
                takenAt: '2024-01-15T14:30:00Z',
              },
            },
          ],
          meta: { count: 1 },
        }),
      });

      const photos = await searchImmichPhotos('42');

      expect(fetch).toHaveBeenCalledWith(
        '/api/integrations/immich/search-photos',
        expect.objectContaining({
          method: 'POST',
          credentials: 'include',
          body: JSON.stringify({ journal_id: 42 }),
        })
      );
      expect(photos).toEqual([
        {
          id: 'asset-1',
          thumbnailUrl: '/api/integrations/immich/assets/asset-1/thumbnail',
          originalFileName: 'beach.jpg',
          takenAt: '2024-01-15T14:30:00Z',
        },
      ]);
    });

    it('surfaces the JSON:API error detail on failure', async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({
          errors: [{ detail: 'Immich is not connected.' }],
        }),
      });

      await expect(searchImmichPhotos('42')).rejects.toThrow(
        'Immich is not connected.'
      );
    });
  });

  describe('createImmichAlbum', () => {
    it('maps the camelCase request to the snake_case backend body', async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          data: {
            id: 'album-1',
            type: 'immich-album',
            attributes: {
              journalId: 42,
              assetCount: 2,
              sharedLinkUrl: 'https://immich.example/share/abc',
            },
          },
        }),
      });

      const result = await createImmichAlbum({
        journalId: '42',
        assetIds: ['asset-1', 'asset-2'],
        createSharedLink: true,
      });

      expect(fetch).toHaveBeenCalledWith(
        '/api/integrations/immich/create-album',
        expect.objectContaining({
          method: 'POST',
          credentials: 'include',
          body: JSON.stringify({
            journal_id: 42,
            asset_ids: ['asset-1', 'asset-2'],
            create_shared_link: true,
          }),
        })
      );
      expect(result.data.attributes.sharedLinkUrl).toBe(
        'https://immich.example/share/abc'
      );
    });

    it('surfaces the JSON:API error detail on failure', async () => {
      (fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          errors: [{ detail: 'Journal already has a linked Immich album.' }],
        }),
      });

      await expect(
        createImmichAlbum({
          journalId: '42',
          assetIds: ['asset-1'],
          createSharedLink: false,
        })
      ).rejects.toThrow('Journal already has a linked Immich album.');
    });
  });

  describe('invalid journal ids', () => {
    it('throws before calling the network for a non-numeric id', async () => {
      await expect(searchImmichPhotos('not-a-number')).rejects.toThrow(
        /invalid journal id/i
      );
      await expect(
        createImmichAlbum({
          journalId: 'not-a-number',
          assetIds: ['asset-1'],
          createSharedLink: false,
        })
      ).rejects.toThrow(/invalid journal id/i);
      expect(fetch).not.toHaveBeenCalled();
    });
  });
});
