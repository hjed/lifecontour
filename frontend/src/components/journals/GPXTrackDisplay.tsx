'use client';

import { useMemo, useEffect, useRef } from 'react';
import dynamic from 'next/dynamic';
import { Card } from '@/components/ui/card';
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
  const { tracks, errors } = useMemo(() => {
    if (!routesData) return { tracks: [], errors: [] };

    const parsedTracks: ParsedTrack[] = [];
    const parseErrors: string[] = [];

    for (const route of routesData) {
      const gpxString = route.attributes.gpx_data;
      if (!gpxString) continue;

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

    return { tracks: parsedTracks, errors: parseErrors };
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

  if (isLoading) {
    return (
      <Skeleton
        className='h-[300px] w-full'
        data-testid={testId || 'gpx-loading'}
      />
    );
  }

  if (apiError || tracks.length === 0) {
    return null; // Return nothing if no valid data
  }

  return (
    <div className='space-y-4' data-testid={testId || 'gpx-track-display'}>
      <Card
        className={`relative z-0 h-[350px] overflow-hidden border ${className || ''}`}
      >
        <GPXTrackMap tracks={tracks} />
      </Card>
    </div>
  );
}
