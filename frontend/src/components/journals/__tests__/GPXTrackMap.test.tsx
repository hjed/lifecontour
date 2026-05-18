import React from 'react';
import { render, screen } from '@testing-library/react';
import GPXTrackMap from '../GPXTrackMap';

// Mock react-leaflet
jest.mock('react-leaflet', () => ({
  MapContainer: ({ children }: any) => (
    <div data-testid='map-container'>{children}</div>
  ),
  TileLayer: () => <div data-testid='tile-layer' />,
  Polyline: (props: any) => (
    <div
      data-testid='polyline'
      data-positions={JSON.stringify(props.positions)}
      data-pathoptions={JSON.stringify(props.pathOptions)}
      {...props}
    />
  ),
  CircleMarker: (props: any) => (
    <div
      data-testid='circle-marker'
      data-center={JSON.stringify(props.center)}
      {...props}
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

    expect(screen.getByTestId('polyline')).toBeInTheDocument();
  });
});
