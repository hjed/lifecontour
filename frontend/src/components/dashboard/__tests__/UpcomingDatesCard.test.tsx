/**
 * @jest-environment jsdom
 *
 * The upcoming-dates card (**W30**–**W32**, wireframe gap 2): important contact
 * dates in the coming week, read from the dashboard payload the page already
 * fetched.
 *
 * Rendered over the **real** `useHomeDashboard` hook against a routed `fetch`
 * mock rather than a mocked hook, as the agenda's and the summary's tests are:
 * what the card shows is derived from the section envelope — ready with dates,
 * ready and empty, unavailable — and a card that ignored `status` would pass
 * against a mocked hook.
 *
 * **The show-more is asserted against the request count as well as the DOM.**
 * The whole window travels in the payload precisely so revealing the remainder
 * costs no second round trip (Phase 11's settled shape), and a card that
 * refetched would still look right on screen.
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test-utils';
import { UpcomingDatesCard } from '../UpcomingDatesCard';
import { DashboardSectionStatus } from '@/lib/api/home-dashboard';
import type {
  DashboardSection,
  HomeDashboardResponse,
  HomeDashboardUpcomingDate,
  HomeDashboardUpcomingDates,
} from '@/lib/api/home-dashboard';
import { ImportantDateTypeEnum } from '@/types/contacts';

// jest.setup.ts mocks @/lib/constants but omits the home-dashboard endpoint;
// use the real constants rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const DASHBOARD_URL = '/api/home-dashboard';
const LIST_NAME = 'Upcoming contact dates';
const EMPTY_LINE = 'No important dates in the next seven days.';
const ANCHOR_DATE = '2026-07-31';

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const AUTHENTICATED_SESSION = {
  authenticated: true,
  user: { id: '1', email: 'test@example.com', name: 'Test User' },
};

function upcomingDate(
  overrides: Partial<HomeDashboardUpcomingDate> & { contact_id: number }
): HomeDashboardUpcomingDate {
  return {
    contact_name: `Contact ${overrides.contact_id}`,
    photo_url: null,
    date_type: ImportantDateTypeEnum.BIRTHDAY,
    custom_date_type_name: null,
    occurs_on: '2026-08-01',
    days_away: 1,
    years: 35,
    observed_for_leap_day: false,
    ...overrides,
  };
}

/** Five dates, in the order the server settled on. */
const FIVE_DATES = [1, 2, 3, 4, 5].map(id =>
  upcomingDate({ contact_id: id, days_away: id })
);

function upcomingDates(
  dates: HomeDashboardUpcomingDate[]
): HomeDashboardUpcomingDates {
  return {
    window: { start_date: ANCHOR_DATE, end_date: '2026-08-06', days_ahead: 7 },
    // Named on the wire and derived from the same list here, because the
    // server does not cap: total is what the show-more displays.
    total: dates.length,
    dates,
  };
}

function dashboardDocument(
  section: DashboardSection<HomeDashboardUpcomingDates>
): HomeDashboardResponse {
  return {
    data: {
      type: 'home-dashboards',
      id: 'user-1',
      attributes: {
        summary: { status: DashboardSectionStatus.UNAVAILABLE, data: null },
        agenda: { status: DashboardSectionStatus.UNAVAILABLE, data: null },
        tasks: { status: DashboardSectionStatus.READY, data: {} },
        upcoming_dates: section,
      },
    },
    meta: { anchor: { date: ANCHOR_DATE, timezone: 'Australia/Sydney' } },
  };
}

/** How many times the dashboard endpoint itself was asked. */
function dashboardRequestCount(): number {
  return mockFetch.mock.calls.filter(
    ([input]) => String(input) === DASHBOARD_URL
  ).length;
}

function routeFetch(dashboard: () => Promise<Response>) {
  mockFetch.mockImplementation((input: RequestInfo | URL) => {
    if (String(input) === DASHBOARD_URL) {
      return dashboard();
    }
    return Promise.resolve({
      ok: true,
      json: async () => AUTHENTICATED_SESSION,
    } as Response);
  });
}

function serveSection(section: DashboardSection<HomeDashboardUpcomingDates>) {
  routeFetch(() =>
    Promise.resolve({
      ok: true,
      json: async () => dashboardDocument(section),
    } as Response)
  );
}

function serveReady(dates: HomeDashboardUpcomingDate[]) {
  serveSection({
    status: DashboardSectionStatus.READY,
    data: upcomingDates(dates),
  });
}

function datesList() {
  return screen.getByRole('list', { name: LIST_NAME });
}

function showMore() {
  return screen.queryByRole('button', { name: /show all/i });
}

describe('UpcomingDatesCard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  describe('with dates in the window', () => {
    it('caps the list at three, as the wireframe draws it', async () => {
      serveReady(FIVE_DATES);

      renderWithProviders(<UpcomingDatesCard />);

      const rows = await within(datesList()).findAllByRole('listitem');
      expect(rows).toHaveLength(3);
    });

    it("keeps the server's order and does not re-sort", async () => {
      // Date ascending, then contact importance descending, is the server's
      // rule — and the payload deliberately publishes none of the importance
      // signals it ranked by, so the card could not reproduce the order even
      // if it tried. It must draw the list it is given.
      serveReady(FIVE_DATES);

      renderWithProviders(<UpcomingDatesCard />);

      const rows = await within(datesList()).findAllByRole('listitem');
      expect(
        rows.map(row => within(row).getByRole('link').textContent)
      ).toEqual(['Contact 1', 'Contact 2', 'Contact 3']);
    });

    it('names the whole window on the show-more, not what is hidden', async () => {
      serveReady(FIVE_DATES);

      renderWithProviders(<UpcomingDatesCard />);

      expect(
        await screen.findByRole('button', { name: /show all/i })
      ).toHaveTextContent('Show all 5 this week');
    });

    it('reveals the remainder in place', async () => {
      serveReady(FIVE_DATES);
      const user = userEvent.setup();

      renderWithProviders(<UpcomingDatesCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );

      expect(within(datesList()).getAllByRole('listitem')).toHaveLength(5);
    });

    it('costs no second request to reveal them', async () => {
      serveReady(FIVE_DATES);
      const user = userEvent.setup();

      renderWithProviders(<UpcomingDatesCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );
      await within(datesList()).findAllByRole('listitem');

      expect(dashboardRequestCount()).toBe(1);
    });

    it('withdraws the show-more once everything is shown', async () => {
      serveReady(FIVE_DATES);
      const user = userEvent.setup();

      renderWithProviders(<UpcomingDatesCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );

      expect(showMore()).not.toBeInTheDocument();
    });

    it('offers no show-more when the window fits', async () => {
      serveReady(FIVE_DATES.slice(0, 3));

      renderWithProviders(<UpcomingDatesCard />);

      expect(await within(datesList()).findAllByRole('listitem')).toHaveLength(
        3
      );
      expect(showMore()).not.toBeInTheDocument();
    });

    it('says nothing about an empty week while it holds dates', async () => {
      serveReady(FIVE_DATES);

      renderWithProviders(<UpcomingDatesCard />);
      await within(datesList()).findAllByRole('listitem');

      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
    });
  });

  describe('with nothing in the window', () => {
    it('says so in one line, reading as a good outcome', async () => {
      serveReady([]);

      renderWithProviders(<UpcomingDatesCard />);

      expect(await screen.findByText(EMPTY_LINE)).toBeInTheDocument();
      // No error styling, no retry: W29's idiom is a quiet line, not a failure.
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('offers no show-more', async () => {
      serveReady([]);

      renderWithProviders(<UpcomingDatesCard />);
      await screen.findByText(EMPTY_LINE);

      expect(showMore()).not.toBeInTheDocument();
    });
  });

  // Three states that all render no rows, kept apart on purpose: "nothing
  // coming up" is a real answer, while a section that has not answered and one
  // that came back unavailable have nothing to claim about the week.
  describe('with no list to draw', () => {
    it('does not claim an empty week while the query is in flight', async () => {
      serveReady([]);

      renderWithProviders(<UpcomingDatesCard />);

      expect(screen.getByTestId('upcoming-dates-loading')).toBeInTheDocument();
      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
      // Settle the query so the test does not leak an update into the next.
      await screen.findByText(EMPTY_LINE);
    });

    it('does not claim an empty week when the section is unavailable', async () => {
      serveSection({
        status: DashboardSectionStatus.UNAVAILABLE,
        data: null,
      });

      renderWithProviders(<UpcomingDatesCard />);

      expect(
        await screen.findByTestId('upcoming-dates-unavailable')
      ).toBeInTheDocument();
      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
    });

    it('keeps the labelled list in place whatever it holds', async () => {
      // W4 asks for a labelled list per section whether or not it has entries,
      // and a hidden one is out of the accessibility tree.
      serveSection({
        status: DashboardSectionStatus.UNAVAILABLE,
        data: null,
      });

      renderWithProviders(<UpcomingDatesCard />);
      await screen.findByTestId('upcoming-dates-unavailable');

      expect(datesList()).toBeInTheDocument();
    });
  });

  it('carries its wireframe header', async () => {
    serveReady([]);

    renderWithProviders(<UpcomingDatesCard />);

    expect(
      screen.getByRole('heading', { level: 3, name: 'Upcoming dates' })
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        'Important dates for your contacts over the next seven days.'
      )
    ).toBeInTheDocument();
    await screen.findByText(EMPTY_LINE);
  });
});
