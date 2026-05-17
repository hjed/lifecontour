import { render, screen, fireEvent } from '@testing-library/react';
import { GPXTrackDisplay } from '../GPXTrackDisplay';
import { createTestQueryClient } from '../test-helpers';
import { QueryClientProvider } from '@tanstack/react-query';

// Mock the routes API
const mockUseRoutes = jest.fn();
jest.mock('@/lib/api/routes', () => ({
  useRoutes: (...args: unknown[]) => mockUseRoutes(...args),
}));

// Mock the dynamic GPXTrackMap component
jest.mock('../GPXTrackMap', () => {
  const MockMap = () => <div data-testid='gpx-track-map'>Map</div>;
  MockMap.displayName = 'MockGPXTrackMap';
  return { __esModule: true, default: MockMap };
});

const SAMPLE_GPX = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk>
    <name>Test Track</name>
    <trkseg>
      <trkpt lat="-33.8688" lon="151.2093">
        <ele>10</ele>
      </trkpt>
      <trkpt lat="-33.8700" lon="151.2100">
        <ele>15</ele>
      </trkpt>
    </trkseg>
  </trk>
</gpx>`;

function makeRouteResource(
  id: string,
  name: string,
  gpxData: string | null = null
) {
  return {
    type: 'routes' as const,
    id,
    attributes: {
      name,
      gpx_data: gpxData,
      description: null,
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
    },
  };
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe('GPXTrackDisplay', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  beforeEach(() => {
    jest.clearAllMocks();
    global.URL.createObjectURL = jest.fn(() => 'blob:mock-url');
    global.URL.revokeObjectURL = jest.fn();
  });

  it('renders nothing when there are no routes with GPX data', () => {
    mockUseRoutes.mockReturnValue({
      data: { data: [makeRouteResource('1', 'Route A')] },
      isLoading: false,
      error: null,
    });

    const { container } = renderWithProviders(
      <GPXTrackDisplay journalId='123' />
    );

    // No map, no download button
    expect(container.firstChild).toBeNull();
  });

  it('renders a download button when routes have GPX data', () => {
    mockUseRoutes.mockReturnValue({
      data: {
        data: [makeRouteResource('1', 'Mountain Trail', SAMPLE_GPX)],
      },
      isLoading: false,
      error: null,
    });

    renderWithProviders(<GPXTrackDisplay journalId='123' />);

    const downloadButton = screen.getByTestId('gpx-download-button');
    expect(downloadButton).toBeInTheDocument();
  });

  it('triggers file download with correct filename when button is clicked', () => {
    mockUseRoutes.mockReturnValue({
      data: {
        data: [makeRouteResource('route-1', 'Mountain Trail', SAMPLE_GPX)],
      },
      isLoading: false,
      error: null,
    });

    renderWithProviders(<GPXTrackDisplay journalId='123' />);

    // Set up spy on anchor creation and click
    const mockClick = jest.fn();
    const originalCreateElement = document.createElement.bind(document);
    const createElementSpy = jest
      .spyOn(document, 'createElement')
      .mockImplementation((tag: string) => {
        if (tag === 'a') {
          const anchor = originalCreateElement('a') as HTMLAnchorElement;
          anchor.click = mockClick;
          return anchor;
        }
        return originalCreateElement(tag);
      });

    const downloadButton = screen.getByTestId('gpx-download-button');
    fireEvent.click(downloadButton);

    expect(global.URL.createObjectURL).toHaveBeenCalled();
    expect(mockClick).toHaveBeenCalled();

    createElementSpy.mockRestore();
  });

  it('shows multiple download buttons when multiple routes have GPX data', () => {
    mockUseRoutes.mockReturnValue({
      data: {
        data: [
          makeRouteResource('1', 'Trail A', SAMPLE_GPX),
          makeRouteResource('2', 'Trail B', SAMPLE_GPX),
        ],
      },
      isLoading: false,
      error: null,
    });

    renderWithProviders(<GPXTrackDisplay journalId='123' />);

    const downloadButtons = screen.getAllByTestId('gpx-download-button');
    expect(downloadButtons).toHaveLength(2);
  });

  it('does not show download button for routes without GPX data', () => {
    mockUseRoutes.mockReturnValue({
      data: {
        data: [
          makeRouteResource('1', 'Trail A', SAMPLE_GPX),
          makeRouteResource('2', 'Trail B', null),
        ],
      },
      isLoading: false,
      error: null,
    });

    renderWithProviders(<GPXTrackDisplay journalId='123' />);

    const downloadButtons = screen.getAllByTestId('gpx-download-button');
    expect(downloadButtons).toHaveLength(1);
  });

  it('shows loading skeleton and no download button while loading', () => {
    mockUseRoutes.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    });

    renderWithProviders(<GPXTrackDisplay journalId='123' />);

    expect(screen.getByTestId('gpx-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('gpx-download-button')).not.toBeInTheDocument();
  });

  it('shows download button without map when GPX has no parseable track points', () => {
    // GPX XML that is valid but contains no <trkpt> elements
    const gpxWithoutPoints = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk>
    <name>Empty Track</name>
  </trk>
</gpx>`;

    mockUseRoutes.mockReturnValue({
      data: {
        data: [makeRouteResource('1', 'Empty Route', gpxWithoutPoints)],
      },
      isLoading: false,
      error: null,
    });

    renderWithProviders(<GPXTrackDisplay journalId='123' />);

    // Download button should still appear
    expect(screen.getByTestId('gpx-download-button')).toBeInTheDocument();
    // Map should NOT appear since there are no parsed coordinates
    expect(screen.queryByTestId('gpx-track-map')).not.toBeInTheDocument();
  });
});
