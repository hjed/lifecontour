/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { OutdoorLogbookStats } from '../OutdoorLogbookStats';
import { JournalType } from '@/types/journals';
import * as dashboardApi from '@/lib/api/outdoor-dashboard';
import * as incompleteApi from '@/lib/api/incomplete-outdoor-activities';
import type {
  OutdoorDashboardAttributes,
  OutdoorDashboardResponse,
} from '@/lib/api/outdoor-dashboard';
import type { IncompleteOutdoorActivityResource } from '@/lib/api/incomplete-outdoor-activities';

jest.mock('@/lib/api/outdoor-dashboard', () => ({
  useOutdoorDashboard: jest.fn(),
}));

jest.mock('@/lib/api/incomplete-outdoor-activities', () => ({
  useIncompleteOutdoorActivities: jest.fn(),
}));

const mockUseOutdoorDashboard = dashboardApi.useOutdoorDashboard as jest.Mock;
const mockUseIncomplete =
  incompleteApi.useIncompleteOutdoorActivities as jest.Mock;

function makeDashboardData(
  overrides: Partial<OutdoorDashboardAttributes> = {}
): OutdoorDashboardResponse {
  return {
    data: {
      type: 'outdoor-dashboards',
      id: 'user-1',
      attributes: {
        upcoming_activities: [],
        checked_out_gear: [],
        activity_totals: {
          last_30_days: {},
          last_365_days: {},
          total_last_30_days: 0,
          total_last_365_days: 0,
        },
        templates_done: {},
        templates_done_last_30_days: 0,
        ...overrides,
      },
    },
  };
}

function makeUpcoming(journalId: number) {
  return {
    journal_id: journalId,
    title: `Trip ${journalId}`,
    event_date_range: {
      start: '2026-08-01T12:00:00Z',
      end: '2026-08-01T12:00:00Z',
    },
    subtypes: [JournalType.CANYONING],
    is_planning: false,
  };
}

function makeIncompleteEntry(
  id: string,
  dismissed = false
): IncompleteOutdoorActivityResource {
  return {
    type: 'incomplete-outdoor-activities',
    id,
    attributes: {
      title: `Entry ${id}`,
      event_date_range: {
        start: '2026-06-01T12:00:00Z',
        end: '2026-06-01T12:00:00Z',
      },
      subtypes: [JournalType.CANYONING],
      reasons: ['no_attributes'],
      dismissed,
    },
  };
}

function statValue(testId: string): string | null {
  return within(screen.getByTestId(testId)).getByTestId('stat-value')
    .textContent;
}

describe('OutdoorLogbookStats', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData(),
      isLoading: false,
      error: null,
    });
    mockUseIncomplete.mockReturnValue({
      data: { data: [] },
      isLoading: false,
      error: null,
    });
  });

  it('renders skeletons while either source is loading', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    });

    render(<OutdoorLogbookStats />);

    expect(screen.getByTestId('logbook-stats-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('logbook-stats-ready')).not.toBeInTheDocument();
  });

  it('renders zeroes rather than an error banner when a source fails', () => {
    // The widgets below already report the failure; a second banner here
    // would just duplicate it.
    mockUseOutdoorDashboard.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Session expired'),
    });

    render(<OutdoorLogbookStats />);

    expect(screen.getByTestId('logbook-stats-ready')).toBeInTheDocument();
    expect(screen.queryByText(/session expired/i)).not.toBeInTheDocument();
    expect(statValue('logbook-stat-activities')).toBe('0');
  });

  it('counts upcoming activities, templates done recently and activities logged', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData({
        upcoming_activities: [makeUpcoming(1), makeUpcoming(2)],
        activity_totals: {
          last_30_days: { [JournalType.CANYONING]: 4 },
          last_365_days: { [JournalType.CANYONING]: 9 },
          total_last_30_days: 3,
          total_last_365_days: 8,
        },
        templates_done_last_30_days: 5,
      }),
      isLoading: false,
      error: null,
    });

    render(<OutdoorLogbookStats />);

    expect(statValue('logbook-stat-upcoming')).toBe('2');
    expect(statValue('logbook-stat-templates')).toBe('5');
    // The distinct-journal total, not the sum of the per-type buckets.
    expect(statValue('logbook-stat-activities')).toBe('3');
  });

  it('counts only non-dismissed entries as needing attention', () => {
    mockUseIncomplete.mockReturnValue({
      data: {
        data: [
          makeIncompleteEntry('1'),
          makeIncompleteEntry('2'),
          makeIncompleteEntry('3', true),
        ],
      },
      isLoading: false,
      error: null,
    });

    render(<OutdoorLogbookStats />);

    expect(statValue('logbook-stat-incomplete')).toBe('2');
  });

  it('labels each tile so the numbers are readable on their own', () => {
    render(<OutdoorLogbookStats />);

    expect(screen.getByTestId('logbook-stat-incomplete')).toHaveTextContent(
      'Incomplete activities'
    );
    expect(screen.getByTestId('logbook-stat-upcoming')).toHaveTextContent(
      'Upcoming'
    );
    expect(screen.getByTestId('logbook-stat-templates')).toHaveTextContent(
      'Templates done'
    );
    expect(screen.getByTestId('logbook-stat-activities')).toHaveTextContent(
      'Activities logged'
    );
  });
});
