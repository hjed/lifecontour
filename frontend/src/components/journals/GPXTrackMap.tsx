'use client';

import { useEffect } from 'react';
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';
import {
  MapContainer,
  TileLayer,
  Polyline,
  Marker,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';

// Fix for default marker icons in Leaflet with webpack/Next.js
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x.src,
  iconUrl: markerIcon.src,
  shadowUrl: markerShadow.src,
});

interface Coordinate {
  latitude: number;
  longitude: number;
  elevation?: number;
  timestamp?: string;
}

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
  if (!coordinates || coordinates.length === 0) return null;

  const positions: [number, number][] = coordinates.map(c => [
    c.latitude,
    c.longitude,
  ]);
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
      {startPoint && <Marker position={startPoint} />}
      {endPoint && !isLoop && <Marker position={endPoint} />}
      <MapBounds coordinates={coordinates} />
    </MapContainer>
  );
}
