/**
 * JournalTypeDataDisplay component for displaying type-specific data.
 *
 * Renders different UI based on journal type (MOOD, PLAN, TRAVEL, PHOTO_ALBUM).
 * Shows read-only view of type-specific data with appropriate formatting.
 */

'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Smile,
  FileText,
  Plane,
  Image as ImageIcon,
  MapPin,
  Hotel,
  Car,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  JournalType,
  type JournalTypeData,
  type MoodData,
  type PlanData,
  type TravelData,
  type PhotoAlbumData,
} from '@/types/journals';

interface JournalTypeDataDisplayProps {
  readonly types: JournalType[];
  readonly typeData?: Record<string, JournalTypeData>;
  readonly className?: string;
}

/**
 * Display component for type-specific journal data.
 * Renders appropriate UI based on journal types.
 */
export function JournalTypeDataDisplay({
  types,
  typeData,
  className,
}: JournalTypeDataDisplayProps) {
  if (!typeData || Object.keys(typeData).length === 0) {
    return null;
  }

  return (
    <div className={cn('space-y-4', className)} data-testid='type-data-display'>
      {types.includes(JournalType.MOOD_RATING) && typeData.MOOD && (
        <MoodDataDisplay data={typeData.MOOD as MoodData} />
      )}
      {types.includes(JournalType.PLAN) && typeData.PLAN && (
        <PlanDataDisplay data={typeData.PLAN as PlanData} />
      )}
      {types.includes(JournalType.TRAVEL) && typeData.TRAVEL && (
        <TravelDataDisplay data={typeData.TRAVEL as TravelData} />
      )}
      {types.includes(JournalType.PHOTO_ALBUM) && typeData.PHOTO_ALBUM && (
        <PhotoAlbumDataDisplay data={typeData.PHOTO_ALBUM as PhotoAlbumData} />
      )}
    </div>
  );
}

// MOOD Data Display
function MoodDataDisplay({ data }: { data: MoodData }) {
  return (
    <Card data-testid='mood-data'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2 text-base'>
          <Smile className='h-4 w-4' />
          Mood & Energy
        </CardTitle>
      </CardHeader>
      <CardContent className='space-y-2'>
        {data.mood_value !== null && data.mood_value !== undefined && (
          <div className='flex items-center justify-between'>
            <span className='text-muted-foreground text-sm'>Mood:</span>
            <Badge variant='secondary'>
              {data.mood_label || `${data.mood_value}/10`}
            </Badge>
          </div>
        )}
        {data.energy_level !== null && data.energy_level !== undefined && (
          <div className='flex items-center justify-between'>
            <span className='text-muted-foreground text-sm'>Energy:</span>
            <Badge variant='secondary'>{data.energy_level}/10</Badge>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// PLAN Data Display
function PlanDataDisplay({ data }: { data: PlanData }) {
  if (!data.documents || data.documents.length === 0) {
    return null;
  }

  return (
    <Card data-testid='plan-data'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2 text-base'>
          <FileText className='h-4 w-4' />
          Plan Documents
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className='space-y-2'>
          {data.documents
            .sort((a, b) => (a.order || 0) - (b.order || 0))
            .map((doc, index) => (
              <div
                key={doc.id || index}
                className='space-y-1 rounded-lg border p-3'
              >
                {doc.title && (
                  <div className='text-sm font-medium'>{doc.title}</div>
                )}
                {doc.description && (
                  <div className='text-muted-foreground text-sm'>
                    {doc.description}
                  </div>
                )}
              </div>
            ))}
        </div>
      </CardContent>
    </Card>
  );
}

// TRAVEL Data Display
function TravelDataDisplay({ data }: { data: TravelData }) {
  const hasFlights = data.flights && data.flights.length > 0;
  const hasAccommodations =
    data.accommodations && data.accommodations.length > 0;
  const hasTransportation =
    data.transportation && data.transportation.length > 0;

  if (!hasFlights && !hasAccommodations && !hasTransportation) {
    return null;
  }

  return (
    <Card data-testid='travel-data'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2 text-base'>
          <Plane className='h-4 w-4' />
          Travel Details
        </CardTitle>
      </CardHeader>
      <CardContent className='space-y-4'>
        {/* Flights */}
        {hasFlights && (
          <div className='space-y-2'>
            <div className='flex items-center gap-2 text-sm font-medium'>
              <Plane className='h-3 w-3' />
              Flights
            </div>
            {data.flights
              .sort((a, b) => (a.order || 0) - (b.order || 0))
              .map((flight, index) => (
                <div
                  key={flight.id || index}
                  className='space-y-1 rounded-lg border p-3 text-sm'
                >
                  {flight.flight_number && (
                    <div className='font-medium'>{flight.flight_number}</div>
                  )}
                  {(flight.departure_airport || flight.arrival_airport) && (
                    <div className='text-muted-foreground'>
                      {flight.departure_airport} → {flight.arrival_airport}
                    </div>
                  )}
                  {flight.booking_reference && (
                    <div className='text-muted-foreground text-xs'>
                      Ref: {flight.booking_reference}
                    </div>
                  )}
                </div>
              ))}
          </div>
        )}

        {/* Accommodations */}
        {hasAccommodations && (
          <div className='space-y-2'>
            <div className='flex items-center gap-2 text-sm font-medium'>
              <Hotel className='h-3 w-3' />
              Accommodations
            </div>
            {data.accommodations
              .sort((a, b) => (a.order || 0) - (b.order || 0))
              .map((acc, index) => (
                <div
                  key={acc.id || index}
                  className='space-y-1 rounded-lg border p-3 text-sm'
                >
                  {acc.name && <div className='font-medium'>{acc.name}</div>}
                  {acc.location && (
                    <div className='text-muted-foreground flex items-center gap-1'>
                      <MapPin className='h-3 w-3' />
                      {acc.location}
                    </div>
                  )}
                  {acc.booking_reference && (
                    <div className='text-muted-foreground text-xs'>
                      Ref: {acc.booking_reference}
                    </div>
                  )}
                </div>
              ))}
          </div>
        )}

        {/* Transportation */}
        {hasTransportation && (
          <div className='space-y-2'>
            <div className='flex items-center gap-2 text-sm font-medium'>
              <Car className='h-3 w-3' />
              Transportation
            </div>
            {data.transportation
              .sort((a, b) => (a.order || 0) - (b.order || 0))
              .map((trans, index) => (
                <div
                  key={trans.id || index}
                  className='space-y-1 rounded-lg border p-3 text-sm'
                >
                  {trans.type && (
                    <div className='font-medium'>{trans.type}</div>
                  )}
                  {trans.details && (
                    <div className='text-muted-foreground'>{trans.details}</div>
                  )}
                  {trans.booking_reference && (
                    <div className='text-muted-foreground text-xs'>
                      Ref: {trans.booking_reference}
                    </div>
                  )}
                </div>
              ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// PHOTO_ALBUM Data Display
function PhotoAlbumDataDisplay({ data }: { data: PhotoAlbumData }) {
  if (!data.immich_album_id) {
    return null;
  }

  return (
    <Card data-testid='photo-album-data'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2 text-base'>
          <ImageIcon className='h-4 w-4' />
          Photo Album
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className='text-muted-foreground text-sm'>
          Album ID: {data.immich_album_id}
        </div>
      </CardContent>
    </Card>
  );
}
