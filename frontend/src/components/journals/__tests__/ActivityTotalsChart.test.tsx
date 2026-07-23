/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { ActivityTotalsChart } from '../ActivityTotalsChart';
import { JournalType } from '@/types/journals';
import * as dashboardApi from '@/lib/api/outdoor-dashboard';
import type {
  OutdoorActivityTotals,
  OutdoorDashboardResponse,
} from '@/lib/api/outdoor-dashboard';

// Mock the API hooks module
jest.mock('@/lib/api/outdoor-dashboard', () => ({
  useOutdoorDashboard: jest.fn(),
}));

const mockUseOutdoorDashboard = dashboardApi.useOutdoorDashboard as jest.Mock;

function makeTotals(
  overrides: Partial<OutdoorActivityTotals> = {}
): OutdoorActivityTotals {
  return {
    last_30_days: {},
    last_365_days: {},
    total_last_30_days: 0,
    total_last_365_days: 0,
    ...overrides,
  };
}

function makeDashboardData(
  totals: OutdoorActivityTotals
): OutdoorDashboardResponse {
  return {
    data: {
      type: 'outdoor-dashboards',
      id: 'user-1',
      attributes: {
        upcoming_activities: [],
        checked_out_gear: [],
        activity_totals: totals,
        templates_done: {},
        templates_done_last_30_days: 0,
      },
    },
  };
}

describe('ActivityTotalsChart', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData(
        makeTotals({
          last_30_days: { [JournalType.CANYONING]: 1 },
          last_365_days: { [JournalType.CANYONING]: 3 },
        })
      ),
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

    render(<ActivityTotalsChart />);

    expect(screen.getByTestId('totals-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('totals-ready')).not.toBeInTheDocument();
  });

  it('renders a destructive alert on error', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Session expired'),
    });

    render(<ActivityTotalsChart />);

    const alert = screen.getByTestId('totals-error');
    expect(alert).toHaveTextContent('Session expired');
    expect(screen.queryByTestId('totals-ready')).not.toBeInTheDocument();
  });

  it('renders the empty state when both windows are empty', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData(makeTotals()),
      isLoading: false,
      error: null,
    });

    render(<ActivityTotalsChart />);

    expect(screen.getByTestId('totals-ready')).toBeInTheDocument();
    expect(screen.getByTestId('totals-empty-state')).toHaveTextContent(
      /no outdoor activity recorded/i
    );
    expect(
      screen.queryByTestId('activity-totals-chart')
    ).not.toBeInTheDocument();
  });

  it('renders a row per type across the union of windows with 0 for missing counts', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData(
        makeTotals({
          last_30_days: { [JournalType.CANYONING]: 1 },
          last_365_days: {
            [JournalType.BUSHWALKING]: 4,
            [JournalType.CANYONING]: 3,
          },
        })
      ),
      isLoading: false,
      error: null,
    });

    render(<ActivityTotalsChart />);

    // Union row set: bushwalking appears only in the 365-day window
    const canyoningRow = screen.getByTestId('totals-row-canyoning');
    expect(
      within(canyoningRow).getByTestId('totals-30d-canyoning')
    ).toHaveTextContent('1');
    expect(
      within(canyoningRow).getByTestId('totals-365d-canyoning')
    ).toHaveTextContent('3');

    const bushwalkingRow = screen.getByTestId('totals-row-bushwalking');
    expect(
      within(bushwalkingRow).getByTestId('totals-30d-bushwalking')
    ).toHaveTextContent('0');
    expect(
      within(bushwalkingRow).getByTestId('totals-365d-bushwalking')
    ).toHaveTextContent('4');
  });

  it('scales both bars against the largest 365-day count', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData(
        makeTotals({
          last_30_days: { [JournalType.CANYONING]: 5 },
          last_365_days: {
            [JournalType.BUSHWALKING]: 20,
            [JournalType.CANYONING]: 10,
          },
        })
      ),
      isLoading: false,
      error: null,
    });

    render(<ActivityTotalsChart />);

    // Max across the chart is bushwalking's 20, so canyoning's 10/5 are
    // half/quarter width — the bars stay comparable between rows. Bar testids
    // are suffixed per type so they're unambiguous without scoping.
    expect(screen.getByTestId('totals-bar-365d-canyoning')).toHaveStyle({
      width: '50%',
    });
    expect(screen.getByTestId('totals-bar-30d-canyoning')).toHaveStyle({
      width: '25%',
    });

    expect(screen.getByTestId('totals-bar-365d-bushwalking')).toHaveStyle({
      width: '100%',
    });
    expect(screen.getByTestId('totals-bar-30d-bushwalking')).toHaveStyle({
      width: '0%',
    });
  });

  it('names each row and states both counts for screen readers', () => {
    render(<ActivityTotalsChart />);

    const row = screen.getByTestId('totals-row-canyoning');
    expect(row).toHaveTextContent('Canyoning');
    // The bars are decorative, so the counts must be readable as text.
    expect(row).toHaveTextContent(
      /1 in the last 30 days, 3 in the last 365 days/i
    );
  });

  it('exposes the rows as a labelled list', () => {
    render(<ActivityTotalsChart />);

    expect(
      screen.getByRole('list', { name: /outdoor activity counts by type/i })
    ).toBeInTheDocument();
  });
});
