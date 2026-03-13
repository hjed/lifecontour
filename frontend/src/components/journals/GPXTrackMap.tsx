'use client';

import { useEffect, useMemo } from 'react';

import {
  MapContainer,
  TileLayer,
  Polyline,
  CircleMarker,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';

import { Coordinate } from '@/types/journals';

interface GPXTrackMapProps {
  readonly tracks: Coordinate[][];
}

// Helper to fit bounds to polyline
function MapBounds({ tracks }: { readonly tracks: Coordinate[][] }) {
  const map = useMap();

  useEffect(() => {
    const allCoordinates = tracks.flat();
    if (allCoordinates.length > 0) {
      const latLngs = allCoordinates.map(c =>
        L.latLng(c.latitude, c.longitude)
      );
      const bounds = L.latLngBounds(latLngs);
      map.fitBounds(bounds, { padding: [20, 20] });
    }
  }, [tracks, map]);

  return null;
}

export default function GPXTrackMap({ tracks }: GPXTrackMapProps) {
  const allPositions = useMemo(
    () =>
      tracks.map(track =>
        track.map(c => [c.latitude, c.longitude] as [number, number])
      ),
    [tracks]
  );

  if (
    !tracks ||
    tracks.length === 0 ||
    allPositions.length === 0 ||
    allPositions[0].length === 0
  )
    return null;

  // Use the first point of the first track as the initial center
  const centerPoint = allPositions[0][0];

  return (
    <MapContainer
      center={centerPoint}
      zoom={13}
      style={{ height: '100%', width: '100%' }}
      scrollWheelZoom={false}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
        url='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
      />

      {allPositions.map((positions, i) => {
        if (positions.length === 0) return null;
        const startPoint = positions[0];
        const endPoint = positions[positions.length - 1];
        const isLoop =
          positions.length > 1 &&
          startPoint[0] === endPoint[0] &&
          startPoint[1] === endPoint[1];

        // Use different colors for different tracks to distinguish them
        const hues = [220, 340, 160, 40, 280]; // Array of standard pleasant hues from primary
        const hueIndex = i % hues.length;
        const color =
          i === 0 ? 'hsl(var(--primary))' : `hsl(${hues[hueIndex]}, 80%, 45%)`;

        return (
          <div key={i}>
            <Polyline
              positions={positions}
              pathOptions={{ color, weight: 4 }}
            />
            {startPoint && (
              <CircleMarker
                center={startPoint}
                radius={6}
                pathOptions={{
                  color: 'white',
                  fillColor: color,
                  fillOpacity: 1,
                  weight: 2,
                }}
              />
            )}
            {endPoint && !isLoop && (
              <CircleMarker
                center={endPoint}
                radius={6}
                pathOptions={{
                  color: 'white',
                  fillColor: 'hsl(var(--destructive))',
                  fillOpacity: 1,
                  weight: 2,
                }}
              />
            )}
          </div>
        );
      })}

      <MapBounds tracks={tracks} />
    </MapContainer>
  );
}
