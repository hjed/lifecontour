/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { CheckedOutGearList } from '../CheckedOutGearList';
import * as dashboardApi from '@/lib/api/outdoor-dashboard';
import type {
  CheckedOutGearItem,
  OutdoorDashboardResponse,
} from '@/lib/api/outdoor-dashboard';

// Mock the API hooks module
jest.mock('@/lib/api/outdoor-dashboard', () => ({
  useOutdoorDashboard: jest.fn(),
}));

const mockUseOutdoorDashboard = dashboardApi.useOutdoorDashboard as jest.Mock;

function makeGearItem(
  overrides: Partial<CheckedOutGearItem> = {}
): CheckedOutGearItem {
  return {
    gear_item_id: 'gear-1',
    name: 'Static rope 60m',
    checked_out_since: '2026-07-10T12:00:00Z',
    journal_id: 42,
    ...overrides,
  };
}

function makeDashboardData(
  gear: CheckedOutGearItem[]
): OutdoorDashboardResponse {
  return {
    data: {
      type: 'outdoor-dashboards',
      id: 'user-1',
      attributes: {
        upcoming_activities: [],
        checked_out_gear: gear,
        activity_totals: {
          last_30_days: {},
          last_365_days: {},
          total_last_30_days: 0,
          total_last_365_days: 0,
        },
        templates_done: {},
        templates_done_last_30_days: 0,
      },
    },
  };
}

describe('CheckedOutGearList', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData([makeGearItem()]),
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

    render(<CheckedOutGearList />);

    expect(screen.getByTestId('checked-out-gear-loading')).toBeInTheDocument();
    expect(
      screen.queryByTestId('checked-out-gear-ready')
    ).not.toBeInTheDocument();
  });

  it('renders a destructive alert on error', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Session expired'),
    });

    render(<CheckedOutGearList />);

    expect(screen.getByTestId('checked-out-gear-error')).toHaveTextContent(
      'Session expired'
    );
    expect(
      screen.queryByTestId('checked-out-gear-ready')
    ).not.toBeInTheDocument();
  });

  it('renders the empty state when no gear is checked out', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData([]),
      isLoading: false,
      error: null,
    });

    render(<CheckedOutGearList />);

    expect(screen.getByTestId('checked-out-gear-ready')).toBeInTheDocument();
    expect(
      screen.getByTestId('checked-out-gear-empty-state')
    ).toHaveTextContent(/no gear is currently checked out/i);
  });

  it('renders each gear item with its name and checked-out-since date', () => {
    render(<CheckedOutGearList />);

    const item = screen.getByTestId('checked-out-gear-item-gear-1');
    expect(item).toHaveTextContent('Static rope 60m');
    expect(item).toHaveTextContent('10 Jul 2026');
  });

  it('renders gear rows as text without links', () => {
    render(<CheckedOutGearList />);

    const item = screen.getByTestId('checked-out-gear-item-gear-1');
    expect(within(item).queryByRole('link')).not.toBeInTheDocument();
  });

  it('preserves the backend ordering, longest-out first', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData([
        makeGearItem({
          gear_item_id: 'gear-old',
          name: 'Harness',
          checked_out_since: '2026-07-01T12:00:00Z',
        }),
        makeGearItem({
          gear_item_id: 'gear-new',
          name: 'Helmet',
          checked_out_since: '2026-07-15T12:00:00Z',
        }),
      ]),
      isLoading: false,
      error: null,
    });

    render(<CheckedOutGearList />);

    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('Harness');
    expect(items[1]).toHaveTextContent('Helmet');
  });

  it('labels the list for screen readers', () => {
    render(<CheckedOutGearList />);

    expect(
      screen.getByRole('list', { name: 'Gear currently checked out' })
    ).toBeInTheDocument();
  });
});
