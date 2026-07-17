/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { ActivityTotalsTable } from '../ActivityTotalsTable';
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
      },
    },
  };
}

describe('ActivityTotalsTable', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData({
        last_30_days: { [JournalType.CANYONING]: 1 },
        last_365_days: { [JournalType.CANYONING]: 3 },
      }),
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

    render(<ActivityTotalsTable />);

    expect(screen.getByTestId('totals-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('totals-ready')).not.toBeInTheDocument();
  });

  it('renders a destructive alert on error', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Session expired'),
    });

    render(<ActivityTotalsTable />);

    const alert = screen.getByTestId('totals-error');
    expect(alert).toHaveTextContent('Session expired');
    expect(screen.queryByTestId('totals-ready')).not.toBeInTheDocument();
  });

  it('renders the empty state when both windows are empty', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData({ last_30_days: {}, last_365_days: {} }),
      isLoading: false,
      error: null,
    });

    render(<ActivityTotalsTable />);

    expect(screen.getByTestId('totals-ready')).toBeInTheDocument();
    expect(screen.getByTestId('totals-empty-state')).toHaveTextContent(
      /no outdoor activity recorded/i
    );
    expect(
      screen.queryByTestId('activity-totals-table')
    ).not.toBeInTheDocument();
  });

  it('renders a row per type across the union of windows with 0 for missing counts', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData({
        last_30_days: { [JournalType.CANYONING]: 1 },
        last_365_days: {
          [JournalType.BUSHWALKING]: 4,
          [JournalType.CANYONING]: 3,
        },
      }),
      isLoading: false,
      error: null,
    });

    render(<ActivityTotalsTable />);

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

  it('labels rows with type labels and accessible table headers', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData({
        last_30_days: { [JournalType.CANYONING]: 1 },
        last_365_days: { [JournalType.CANYONING]: 3 },
      }),
      isLoading: false,
      error: null,
    });

    render(<ActivityTotalsTable />);

    expect(
      screen.getByRole('columnheader', { name: 'Activity' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('columnheader', { name: 'Last 30 days' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('columnheader', { name: 'Last 365 days' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('rowheader', { name: 'Canyoning' })
    ).toBeInTheDocument();
  });
});
