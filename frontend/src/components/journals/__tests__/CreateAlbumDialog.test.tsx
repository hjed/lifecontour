/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CreateAlbumDialog } from '../CreateAlbumDialog';
import type { ImmichPhoto } from '@/lib/api/immich-albums';

const mockCreateMutate = jest.fn();
const mockUseCreateImmichAlbum = jest.fn();

jest.mock('@/lib/api/immich-albums', () => ({
  useCreateImmichAlbum: () => mockUseCreateImmichAlbum(),
}));

const PHOTOS: ImmichPhoto[] = [
  {
    id: 'asset-1',
    thumbnailUrl: '/thumb/asset-1',
    originalFileName: 'one.jpg',
    takenAt: '2024-01-15T10:00:00Z',
  },
  {
    id: 'asset-2',
    thumbnailUrl: '/thumb/asset-2',
    originalFileName: 'two.jpg',
    takenAt: '2024-01-15T11:00:00Z',
  },
  {
    id: 'asset-3',
    thumbnailUrl: '/thumb/asset-3',
    originalFileName: 'three.jpg',
    takenAt: '2024-01-15T12:00:00Z',
  },
];

function renderDialog() {
  return render(
    <CreateAlbumDialog
      open
      onOpenChange={jest.fn()}
      journalId='42'
      photos={PHOTOS}
    />
  );
}

describe('CreateAlbumDialog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseCreateImmichAlbum.mockReturnValue({
      mutate: mockCreateMutate,
      isPending: false,
    });
  });

  it('selects all photos by default', () => {
    renderDialog();

    for (const photo of PHOTOS) {
      expect(screen.getByTestId(`photo-checkbox-${photo.id}`)).toBeChecked();
    }
    expect(screen.getByTestId('create-album-selected-count')).toHaveTextContent(
      '3 of 3 photos selected'
    );
  });

  it('deselects a photo when its checkbox is toggled', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByTestId('photo-checkbox-asset-2'));

    expect(screen.getByTestId('photo-checkbox-asset-2')).not.toBeChecked();
    expect(screen.getByTestId('create-album-selected-count')).toHaveTextContent(
      '2 of 3 photos selected'
    );
  });

  it('toggles selection when the whole thumbnail tile is clicked', async () => {
    const user = userEvent.setup();
    renderDialog();

    // Clicking the thumbnail image (not the small checkbox) toggles the tile.
    await user.click(screen.getByAltText('two.jpg'));

    expect(screen.getByTestId('photo-checkbox-asset-2')).not.toBeChecked();
    expect(screen.getByTestId('create-album-selected-count')).toHaveTextContent(
      '2 of 3 photos selected'
    );
  });

  it('confirms with only the selected asset ids', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByTestId('photo-checkbox-asset-2'));
    await user.click(screen.getByTestId('create-album-confirm'));

    expect(mockCreateMutate).toHaveBeenCalledWith(
      {
        journalId: '42',
        assetIds: ['asset-1', 'asset-3'],
        createSharedLink: false,
      },
      expect.any(Object)
    );
  });

  it('passes the create-shared-link choice through on confirm', async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByTestId('create-shared-link-checkbox'));
    await user.click(screen.getByTestId('create-album-confirm'));

    expect(mockCreateMutate).toHaveBeenCalledWith(
      expect.objectContaining({ createSharedLink: true }),
      expect.any(Object)
    );
  });

  it('disables confirm when no photos are selected', async () => {
    const user = userEvent.setup();
    renderDialog();

    for (const photo of PHOTOS) {
      await user.click(screen.getByTestId(`photo-checkbox-${photo.id}`));
    }

    expect(screen.getByTestId('create-album-confirm')).toBeDisabled();
  });
});
