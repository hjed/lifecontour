'use client';

import { useMemo, useEffect } from 'react';
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
  const { tracks, errors } = useMemo(() => {
    if (!routesResponse?.data) return { tracks: [], errors: [] };

    const parsedTracks: Coordinate[][] = [];
    const parseErrors: string[] = [];

    for (const route of routesResponse.data) {
      const gpxString = route.attributes.gpx_data;
      if (!gpxString) continue;

      try {
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(gpxString, 'text/xml');

        const parserError = xmlDoc.querySelector('parsererror');
        if (parserError) {
          console.error(
            'Failed to parse GPX data for route',
            route.id,
            parserError.textContent
          );
          parseErrors.push(
            `Contains invalid GPX data in route ${route.attributes.name}`
          );
          continue;
        }

        const trkpts = xmlDoc.getElementsByTagName('trkpt');
        const coordinates: Coordinate[] = [];

        for (let i = 0; i < trkpts.length; i++) {
          const pt = trkpts[i];
          const lat = pt.getAttribute('lat');
          const lon = pt.getAttribute('lon');
          if (lat && lon) {
            coordinates.push({
              latitude: parseFloat(lat),
              longitude: parseFloat(lon),
            });
          }
        }

        if (coordinates.length > 0) {
          parsedTracks.push(coordinates);
        }
      } catch (err) {
        console.error('Failed to parse GPX data for route', route.id, err);
      }
    }

    return { tracks: parsedTracks, errors: parseErrors };
  }, [routesResponse?.data]);

  useEffect(() => {
    if (errors && errors.length > 0) {
      errors.forEach(err => toast.error(err));
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
