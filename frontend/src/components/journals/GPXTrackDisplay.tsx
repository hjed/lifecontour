'use client';

import { useMemo, useEffect, useRef, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { Download } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';

const GPXTrackMap = dynamic(() => import('./GPXTrackMap'), {
  ssr: false,
  loading: () => <Skeleton className='h-full w-full' />,
});

interface GPXTrackDisplayProps {
  readonly journalId: string;
  readonly className?: string;
  readonly 'data-testid'?: string;
}

import { Coordinate } from '@/types/journals';
import { useRoutes } from '@/lib/api/routes';

export interface ParsedTrack {
  id: string;
  coordinates: Coordinate[];
}

/** A route that has valid GPX data available for download. */
interface DownloadableRoute {
  id: string;
  name: string;
  gpxData: string;
}

function parseGPXString(
  gpxString: string,
  routeId: string,
  routeName: string
): { track?: ParsedTrack; error?: string } {
  const parser = new DOMParser();
  const xmlDoc = parser.parseFromString(gpxString, 'text/xml');

  const parserError = xmlDoc.querySelector('parsererror');
  if (parserError) {
    console.error(
      'Failed to parse GPX data for route',
      routeId,
      parserError.textContent
    );
    return {
      error: `Contains invalid GPX data in route ${routeName}`,
    };
  }

  const trkpts = xmlDoc.getElementsByTagName('trkpt');
  const coordinates: Coordinate[] = [];

  for (const pt of Array.from(trkpts)) {
    const lat = pt.getAttribute('lat');
    const lon = pt.getAttribute('lon');
    if (lat && lon) {
      coordinates.push({
        latitude: Number.parseFloat(lat),
        longitude: Number.parseFloat(lon),
      });
    }
  }

  if (coordinates.length > 0) {
    return { track: { id: routeId, coordinates } };
  }
  return {};
}

/**
 * Sanitise a route name so it is safe to use as a download filename.
 *
 * Strips path separators and other characters that are invalid or
 * confusing in filenames across Windows, macOS, and Linux.
 */
function sanitiseFileName(name: string): string {
  return name.replace(/[/\\:*?"<>|]/g, '_').trim() || 'track';
}

/**
 * Trigger a browser file download for a GPX XML string.
 *
 * Creates a temporary Blob URL, programmatically clicks a hidden anchor,
 * then defers URL revocation so the browser has time to start the download.
 */
function downloadGPXFile(gpxData: string, fileName: string): void {
  const blob = new Blob([gpxData], { type: 'application/gpx+xml' });
  const url = URL.createObjectURL(blob);

  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);

  // Defer revocation so the browser has time to initiate the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function GPXTrackDisplay({
  journalId,
  className,
  'data-testid': testId,
}: GPXTrackDisplayProps) {
  const {
    data: routesResponse,
    isLoading,
    error: apiError,
  } = useRoutes(journalId);
  const routesData = routesResponse?.data;
  const { tracks, errors, downloadableRoutes } = useMemo(() => {
    if (!routesData) return { tracks: [], errors: [], downloadableRoutes: [] };

    const parsedTracks: ParsedTrack[] = [];
    const parseErrors: string[] = [];
    const dlRoutes: DownloadableRoute[] = [];

    for (const route of routesData) {
      const gpxString = route.attributes.gpx_data;
      if (!gpxString) continue;

      // Track the route as downloadable regardless of parse success —
      // users may still want the raw file even if coordinates fail to render.
      dlRoutes.push({
        id: route.id,
        name: route.attributes.name,
        gpxData: gpxString,
      });

      try {
        const { track, error } = parseGPXString(
          gpxString,
          route.id,
          route.attributes.name
        );
        if (error) {
          parseErrors.push(error);
        } else if (track) {
          parsedTracks.push(track);
        }
      } catch (err) {
        console.error('Failed to parse GPX data for route', route.id, err);
      }
    }

    return {
      tracks: parsedTracks,
      errors: parseErrors,
      downloadableRoutes: dlRoutes,
    };
  }, [routesData]);

  const toastedErrorsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (errors && errors.length > 0) {
      errors.forEach(err => {
        if (!toastedErrorsRef.current.has(err)) {
          toast.error(err);
          toastedErrorsRef.current.add(err);
        }
      });
    }
  }, [errors]);

  const handleDownload = useCallback((route: DownloadableRoute) => {
    downloadGPXFile(route.gpxData, `${sanitiseFileName(route.name)}.gpx`);
  }, []);

  if (isLoading) {
    return (
      <Skeleton
        className='h-[300px] w-full'
        data-testid={testId || 'gpx-loading'}
      />
    );
  }

  if (apiError || (tracks.length === 0 && downloadableRoutes.length === 0)) {
    return null; // Return nothing if no valid data and nothing downloadable
  }

  return (
    <div className='space-y-4' data-testid={testId || 'gpx-track-display'}>
      {tracks.length > 0 && (
        <Card
          className={`relative z-0 h-[350px] overflow-hidden border ${className || ''}`}
        >
          <GPXTrackMap tracks={tracks} />
        </Card>
      )}

      {downloadableRoutes.length > 0 && (
        <div className='flex flex-wrap gap-2'>
          {downloadableRoutes.map(route => (
            <Button
              key={route.id}
              variant='outline'
              size='sm'
              onClick={() => handleDownload(route)}
              data-testid='gpx-download-button'
              className='gap-1.5'
            >
              <Download className='h-4 w-4' aria-hidden='true' />
              {downloadableRoutes.length > 1
                ? `Download ${route.name}`
                : 'Download GPX'}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
