/**
 * AlbumCoverBanner — displays a PHOTO_ALBUM journal's Immich cover photo.
 *
 * The cover is fetched on-demand from the backend proxy (`cover_url`) and is
 * not persisted. When an `albumUrl` is provided the banner is clickable and
 * opens the album in the Immich web UI. If the image fails to load (Immich
 * unreachable / cover removed) the banner hides itself gracefully.
 */

'use client';

import { useState } from 'react';

interface AlbumCoverBannerProps {
  readonly coverUrl?: string | null;
  readonly albumUrl?: string | null;
  /** Human-readable album label, used for the image/link accessible names. */
  readonly label: string;
}

export function AlbumCoverBanner({
  coverUrl,
  albumUrl,
  label,
}: AlbumCoverBannerProps) {
  const [failed, setFailed] = useState(false);

  if (!coverUrl || failed) {
    return null;
  }

  const image = (
    <img
      src={coverUrl}
      alt={`${label} album cover`}
      data-testid='photo-album-cover'
      className='h-40 w-full rounded-md object-cover'
      onError={() => setFailed(true)}
    />
  );

  if (albumUrl) {
    return (
      <a
        href={albumUrl}
        target='_blank'
        rel='noopener noreferrer'
        data-testid='photo-album-cover-link'
        aria-label={`Open ${label} in Immich`}
        className='block'
      >
        {image}
      </a>
    );
  }

  return image;
}
