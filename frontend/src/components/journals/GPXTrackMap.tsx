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
  readonly coordinates: Coordinate[];
}

// Helper to fit bounds to polyline
function MapBounds({ coordinates }: { readonly coordinates: Coordinate[] }) {
  const map = useMap();

  useEffect(() => {
    if (coordinates.length > 0) {
      const latLngs = coordinates.map(c => L.latLng(c.latitude, c.longitude));
      const bounds = L.latLngBounds(latLngs);
      map.fitBounds(bounds, { padding: [20, 20] });
    }
  }, [coordinates, map]);

  return null;
}

export default function GPXTrackMap({ coordinates }: GPXTrackMapProps) {
  const positions: [number, number][] = useMemo(
    () => (coordinates || []).map(c => [c.latitude, c.longitude]),
    [coordinates]
  );

  if (!coordinates || coordinates.length === 0) return null;
  const startPoint = positions[0];
  const endPoint = positions[positions.length - 1];

  // Compare coordinates to avoid duplicate markers when track starts and ends at the same location
  const isLoop =
    positions.length > 1 &&
    startPoint[0] === endPoint[0] &&
    startPoint[1] === endPoint[1];

  return (
    <MapContainer
      center={startPoint}
      zoom={13}
      style={{ height: '100%', width: '100%' }}
      scrollWheelZoom={false}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
        url='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
      />
      <Polyline
        positions={positions}
        pathOptions={{ color: 'hsl(var(--primary))', weight: 4 }}
      />
      {startPoint && (
        <CircleMarker
          center={startPoint}
          radius={6}
          pathOptions={{
            color: 'white',
            fillColor: 'hsl(var(--primary))',
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
      <MapBounds coordinates={coordinates} />
    </MapContainer>
  );
}
