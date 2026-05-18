import React from 'react';
import { render, screen } from '@testing-library/react';
import GPXTrackMap from '../GPXTrackMap';

// Mock react-leaflet
jest.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid='map-container'>{children}</div>
  ),
  TileLayer: () => <div data-testid='tile-layer' />,
  Polyline: (
    props: React.ComponentProps<'div'> & {
      positions?: [number, number][];
      color?: string;
      weight?: number;
    }
  ) => (
    <div
      data-testid='polyline'
      data-positions={JSON.stringify(props.positions)}
      data-color={props.color}
      data-weight={props.weight}
    />
  ),
  CircleMarker: (
    props: React.ComponentProps<'div'> & {
      center?: [number, number];
      color?: string;
      fillColor?: string;
      fillOpacity?: number;
      weight?: number;
    }
  ) => (
    <div
      data-testid='circle-marker'
      data-center={JSON.stringify(props.center)}
      data-color={props.color}
      data-fillcolor={props.fillColor}
    />
  ),
  useMap: () => ({ fitBounds: jest.fn() }),
}));

describe('GPXTrackMap', () => {
  it('renders track path correctly', () => {
    const tracks = [
      {
        id: '1',
        coordinates: [
          { latitude: 10, longitude: 20 },
          { latitude: 11, longitude: 21 },
          { latitude: 12, longitude: 22 },
        ],
      },
    ];

    render(<GPXTrackMap tracks={tracks} />);

    const polyline = screen.getByTestId('polyline');
    expect(polyline).toBeInTheDocument();

    // Verify direct style props are passed
    expect(polyline).toHaveAttribute('data-color', 'hsl(var(--primary))');
    expect(polyline).toHaveAttribute('data-weight', '4');
  });
});
