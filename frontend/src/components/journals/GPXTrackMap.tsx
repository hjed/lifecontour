'use client';

import React, { useEffect, useMemo } from 'react';

import {
  MapContainer,
  TileLayer,
  Polyline,
  CircleMarker,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';

import type { ParsedTrack } from './GPXTrackDisplay';

interface GPXTrackMapProps {
  readonly tracks: ParsedTrack[];
}

// Leaflet applies `color`/`fillColor` as SVG presentation attributes, which lose
// to any author CSS rule, so these classes win. The chart tokens are the theme's
// categorical series palette and are defined for both light and dark. Class
// strings must be spelled out in full — Tailwind cannot see `stroke-chart-${n}`.
const TRACK_STROKE = [
  'stroke-chart-1',
  'stroke-chart-2',
  'stroke-chart-3',
  'stroke-chart-4',
  'stroke-chart-5',
];
const TRACK_FILL = [
  'fill-chart-1',
  'fill-chart-2',
  'fill-chart-3',
  'fill-chart-4',
  'fill-chart-5',
];

// Helper to fit bounds to polyline
function MapBounds({ tracks }: { readonly tracks: ParsedTrack[] }) {
  const map = useMap();

  useEffect(() => {
    const allCoordinates = tracks.flatMap(t => t.coordinates);
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
  const mappedTracks = useMemo(
    () =>
      tracks.map(track => ({
        id: track.id,
        positions: track.coordinates.map(
          c => [c.latitude, c.longitude] as [number, number]
        ),
      })),
    [tracks]
  );

  if (
    !tracks ||
    tracks.length === 0 ||
    mappedTracks.length === 0 ||
    mappedTracks[0].positions.length === 0
  )
    return null;

  // Use the first point of the first track as the initial center
  const centerPoint = mappedTracks[0].positions[0];

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

      {mappedTracks.map(({ id, positions }, i) => {
        if (positions.length === 0) return null;
        const startPoint = positions[0];
        const endPoint = positions[positions.length - 1];
        const isLoop =
          positions.length > 1 &&
          startPoint[0] === endPoint[0] &&
          startPoint[1] === endPoint[1];

        // Use different colors for different tracks to distinguish them
        const colorIndex = i % TRACK_STROKE.length;

        return (
          <React.Fragment key={id}>
            <Polyline
              positions={positions}
              className={TRACK_STROKE[colorIndex]}
              weight={4}
            />
            {startPoint && (
              <CircleMarker
                center={startPoint}
                radius={6}
                className={`${TRACK_FILL[colorIndex]} stroke-white`}
                fillOpacity={1}
                weight={2}
              />
            )}
            {endPoint && !isLoop && (
              <CircleMarker
                center={endPoint}
                radius={6}
                className='fill-destructive stroke-white'
                fillOpacity={1}
                weight={2}
              />
            )}
          </React.Fragment>
        );
      })}

      <MapBounds tracks={tracks} />
    </MapContainer>
  );
}
