/**
 * @jest-environment jsdom
 */

import { render, screen, within } from '@testing-library/react';
import { TemplatesDoneList } from '../TemplatesDoneList';
import * as dashboardApi from '@/lib/api/outdoor-dashboard';
import type {
  OutdoorDashboardResponse,
  TemplateDone,
} from '@/lib/api/outdoor-dashboard';

// Mock the API hooks module
jest.mock('@/lib/api/outdoor-dashboard', () => ({
  useOutdoorDashboard: jest.fn(),
}));

const mockUseOutdoorDashboard = dashboardApi.useOutdoorDashboard as jest.Mock;

function makeDashboardData(
  templatesDone: Record<string, TemplateDone[]>
): OutdoorDashboardResponse {
  return {
    data: {
      type: 'outdoor-dashboards',
      id: 'user-1',
      attributes: {
        upcoming_activities: [],
        checked_out_gear: [],
        activity_totals: { last_30_days: {}, last_365_days: {} },
        templates_done: templatesDone,
      },
    },
  };
}

const SEEDED: Record<string, TemplateDone[]> = {
  canyoning: [
    { template_id: 'tpl-empress', name: 'Empress Falls', done_count: 3 },
    { template_id: 'tpl-claustral', name: 'Claustral Canyon', done_count: 1 },
  ],
  caving: [{ template_id: 'tpl-jenolan', name: 'Jenolan', done_count: 2 }],
};

describe('TemplatesDoneList', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData(SEEDED),
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

    render(<TemplatesDoneList />);

    expect(screen.getByTestId('templates-done-loading')).toBeInTheDocument();
    expect(
      screen.queryByTestId('templates-done-ready')
    ).not.toBeInTheDocument();
  });

  it('renders a destructive alert on error', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Session expired'),
    });

    render(<TemplatesDoneList />);

    expect(screen.getByTestId('templates-done-error')).toHaveTextContent(
      'Session expired'
    );
    expect(
      screen.queryByTestId('templates-done-ready')
    ).not.toBeInTheDocument();
  });

  it('renders the empty state when no templates have been done', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData({}),
      isLoading: false,
      error: null,
    });

    render(<TemplatesDoneList />);

    expect(screen.getByTestId('templates-done-ready')).toBeInTheDocument();
    expect(screen.getByTestId('templates-done-empty-state')).toHaveTextContent(
      /no templates done yet/i
    );
  });

  it('groups templates under a labelled heading per template type, type-sorted', () => {
    render(<TemplatesDoneList />);

    // The card title is the h3; the type groups nest beneath it as h4s.
    const headings = screen.getAllByRole('heading', { level: 4 });
    expect(headings.map(h => h.textContent)).toEqual(['Canyoning', 'Caving']);

    const canyoningGroup = screen.getByTestId('templates-done-group-canyoning');
    expect(
      within(canyoningGroup).getByRole('list', { name: 'Canyoning' })
    ).toBeInTheDocument();
    expect(within(canyoningGroup).getAllByRole('listitem')).toHaveLength(2);

    const cavingGroup = screen.getByTestId('templates-done-group-caving');
    expect(within(cavingGroup).getAllByRole('listitem')).toHaveLength(1);
  });

  it('links each template to the templates settings section', () => {
    render(<TemplatesDoneList />);

    const item = screen.getByTestId('templates-done-item-tpl-empress');
    expect(
      within(item).getByRole('link', { name: 'Empress Falls' })
    ).toHaveAttribute('href', '/settings#templates');
  });

  it('shows a per-template done-count, pluralised', () => {
    render(<TemplatesDoneList />);

    expect(
      screen.getByTestId('templates-done-count-tpl-empress')
    ).toHaveTextContent('Done 3 times');
    expect(
      screen.getByTestId('templates-done-count-tpl-claustral')
    ).toHaveTextContent('Done 1 time');
  });

  it('falls back to a readable label for template types without a badge label', () => {
    mockUseOutdoorDashboard.mockReturnValue({
      data: makeDashboardData({
        abseiling: [
          { template_id: 'tpl-a', name: 'Cliff drop', done_count: 1 },
        ],
      }),
      isLoading: false,
      error: null,
    });

    render(<TemplatesDoneList />);

    expect(
      screen.getByRole('heading', { level: 4, name: 'Abseiling' })
    ).toBeInTheDocument();
  });
});
