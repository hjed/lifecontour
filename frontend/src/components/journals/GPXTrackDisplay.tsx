'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

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

interface GPXData {
  coordinates: Coordinate[];
  statistics?: unknown;
}

export function GPXTrackDisplay({
  journalId,
  className,
  'data-testid': testId,
}: GPXTrackDisplayProps) {
  const [data, setData] = useState<GPXData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function fetchGPX() {
      try {
        setLoading(true);
        setError(null); // Clear any previous error before each fetch
        const res = await fetch(`/api/journals/${journalId}/gpx`, {
          credentials: 'include',
        });
        if (!res.ok) {
          if (res.status === 404) {
            // It's normal to not have GPX track data sometimes
            if (isMounted) setData(null);
            return;
          }
          throw new Error('Failed to fetch GPX data');
        }

        const json = await res.json();
        if (isMounted && json.data?.attributes) {
          setData(json.data.attributes);
        }
      } catch (err) {
        console.error('Error fetching GPX data:', err);
        if (isMounted) setError('Could not load track data');
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    fetchGPX();

    return () => {
      isMounted = false;
    };
  }, [journalId]);

  if (loading) {
    return (
      <Skeleton
        className='h-[300px] w-full'
        data-testid={testId || 'gpx-loading'}
      />
    );
  }

  if (error || !data?.coordinates?.length) {
    return null; // Return nothing if no valid data
  }

  return (
    <div className='space-y-4' data-testid={testId || 'gpx-track-display'}>
      <Card
        className={`relative z-0 h-[350px] overflow-hidden border ${className || ''}`}
      >
        <GPXTrackMap coordinates={data.coordinates} />
      </Card>
      {/* If stats exists from the GPX endpoint, we could render an ActivityStats here,
          but ActivityStats expects FitnessData shape. We can adapt it if needed, or
          leave it to the JournalTypeDataDisplay to show stats from the main journal type payload. */}
    </div>
  );
}
