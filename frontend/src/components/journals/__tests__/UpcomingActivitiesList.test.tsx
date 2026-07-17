/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { UpcomingActivitiesList } from '../UpcomingActivitiesList';
import { JournalType } from '@/types/journals';
import * as dashboardApi from '@/lib/api/outdoor-dashboard';
import type {
  OutdoorDashboardResponse,
  UpcomingOutdoorActivityEntry,
} from '@/lib/api/outdoor-dashboard';

// Mock the API hooks module
jest.mock('@/lib/api/outdoor-dashboard', () => ({
  useOutdoorDashboard: jest.fn(),
}));

const mockUseOutdoorDashboard = dashboardApi.useOutdoorDashboard as jest.Mock;

function makeUpcomingEntry(
  overrides: Partial<UpcomingOutdoorActivityEntry> = {}
): UpcomingOutdoorActivityEntry {
  return {
    journal_id: 42,
    title: 'Empress Falls Canyon',
    // Noon UTC keeps the local calendar date stable across timezones
    event_date_range: {
      start: '2026-07-20T12:00:00Z',
      end: '2026-07-20T12:00:00Z',
    },
    subtypes: [JournalType.CANYONING],
    is_planning: false,
    ...overrides,
  };
}

function makeDashboardData(
  upcoming: UpcomingOutdoorActivityEntry[]
): OutdoorDashboardResponse {
  return {
    data: {
      type: 'outdoor-dashboards',
      id: 'user-1',
      attributes: {
        upcoming_activities: upcoming,
        checked_out_gear: [],
        activity_totals: { last_30_days: {}, last_365_days: {} },
        templates_done: {},
      },
    },
  };
}

describe('UpcomingActivitiesList', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData([makeUpcomingEntry()]),
      isLoading: false,
      error: null,
    });
  });

  it('renders skeletons while loading', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    });

    render(<UpcomingActivitiesList />);

    expect(screen.getByTestId('upcoming-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('upcoming-ready')).not.toBeInTheDocument();
  });

  it('renders a destructive alert on error', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Session expired'),
    });

    render(<UpcomingActivitiesList />);

    const alert = screen.getByTestId('upcoming-error');
    expect(alert).toHaveTextContent('Session expired');
    expect(screen.queryByTestId('upcoming-ready')).not.toBeInTheDocument();
  });

  it('renders the empty state when there are no upcoming activities', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData([]),
      isLoading: false,
      error: null,
    });

    render(<UpcomingActivitiesList />);

    expect(screen.getByTestId('upcoming-ready')).toBeInTheDocument();
    expect(screen.getByTestId('upcoming-empty-state')).toHaveTextContent(
      /no upcoming outdoor activities/i
    );
  });

  it('renders entries with title links to the journal and formatted dates', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData([
        makeUpcomingEntry(),
        makeUpcomingEntry({
          journal_id: 43,
          title: 'Kanangra Main',
          event_date_range: {
            start: '2026-07-25T12:00:00Z',
            end: '2026-07-26T12:00:00Z',
          },
        }),
      ]),
      isLoading: false,
      error: null,
    });

    render(<UpcomingActivitiesList />);

    const first = screen.getByTestId('upcoming-activity-item-42');
    expect(
      within(first).getByRole('link', { name: 'Empress Falls Canyon' })
    ).toHaveAttribute('href', '/journals/42');
    expect(first).toHaveTextContent('20 Jul 2026');

    const second = screen.getByTestId('upcoming-activity-item-43');
    expect(
      within(second).getByRole('link', { name: 'Kanangra Main' })
    ).toHaveAttribute('href', '/journals/43');
    expect(second).toHaveTextContent('25 - 26 Jul 2026');

    // Server order (soonest first) is preserved, not re-sorted client-side
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveAttribute(
      'data-testid',
      'upcoming-activity-item-42'
    );
    expect(items[1]).toHaveAttribute(
      'data-testid',
      'upcoming-activity-item-43'
    );
  });

  it('shows the Outdoor Planning badge for planning entries', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData([
        makeUpcomingEntry({
          journal_id: 50,
          title: 'Winter Trip Planning',
          subtypes: [],
          is_planning: true,
        }),
      ]),
      isLoading: false,
      error: null,
    });

    render(<UpcomingActivitiesList />);

    const item = screen.getByTestId('upcoming-activity-item-50');
    expect(
      within(item).getByTestId('type-badge-outdoor_planning')
    ).toBeInTheDocument();
  });

  it('falls back to the Outdoor Activity badge when subtypes are empty and not planning', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData([
        makeUpcomingEntry({ journal_id: 51, subtypes: [], is_planning: false }),
      ]),
      isLoading: false,
      error: null,
    });

    render(<UpcomingActivitiesList />);

    const item = screen.getByTestId('upcoming-activity-item-51');
    expect(
      within(item).getByTestId('type-badge-outdoor_activity')
    ).toBeInTheDocument();
  });

  it('renders subtype badges for activity entries', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData([
        makeUpcomingEntry({
          subtypes: [JournalType.CANYONING, JournalType.BUSHWALKING],
        }),
      ]),
      isLoading: false,
      error: null,
    });

    render(<UpcomingActivitiesList />);

    const item = screen.getByTestId('upcoming-activity-item-42');
    expect(
      within(item).getByTestId('type-badge-canyoning')
    ).toBeInTheDocument();
    expect(
      within(item).getByTestId('type-badge-bushwalking')
    ).toBeInTheDocument();
  });
});
