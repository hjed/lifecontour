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

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test-utils';
import {
  DASHBOARD_URL,
  dashboardRequestCount,
} from '@/test-utils/home-dashboard';
import {
  UpcomingDatesCard,
  VISIBLE_UPCOMING_DATES,
} from '../UpcomingDatesCard';
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
    // `end_date` is `ANCHOR_DATE` plus `days_ahead`; it read 08-06 and the
    // three fields disagreed, which is a window the endpoint cannot send.
    window: { start_date: ANCHOR_DATE, end_date: '2026-08-07', days_ahead: 7 },
    // Named on the wire and derived from the same list here, because the
    // server does not cap. The show-more names the list, not this — see the
    // disagreeing-total cases below.
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
        // Ready and empty in the shape the endpoint sends since Phase 13.
        // These suites are about the card beside it, so the section stays a
        // real answer holding nothing rather than an unavailable one.
        tasks: {
          status: DashboardSectionStatus.READY,
          data: {
            window: {
              start_date: '2026-07-31',
              end_date: '2026-08-07',
              days_ahead: 7,
            },
            total: 0,
            tasks: [],
          },
        },
        upcoming_dates: section,
      },
    },
    meta: { anchor: { date: ANCHOR_DATE, timezone: 'Australia/Sydney' } },
  };
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

    /**
     * **The show-more names the list it reveals, not `total`** (ITER18-004
     * Phase 18). The card offers the button against the list's own length, and
     * it used to *name* `total` — two quantities for one button, which agree
     * on every payload the endpoint sends, so nothing could catch it. The list
     * won, on the reasoning `TasksCard` records: a button names what pressing
     * it reveals, and were the two ever to disagree, `total` is the half that
     * is not true on screen. Both directions, because a `total` below the list
     * must neither hide the button nor under-name it.
     */
    it.each([
      ['exceeds', 9],
      ['falls short of', 2],
    ])(
      'names the five it holds when total %s the list',
      async (_direction, total) => {
        serveSection({
          status: DashboardSectionStatus.READY,
          data: { ...upcomingDates(FIVE_DATES), total },
        });

        renderWithProviders(<UpcomingDatesCard />);

        expect(
          await screen.findByRole('button', { name: /show all/i })
        ).toHaveTextContent('Show all 5 this week');
      }
    );

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

      expect(dashboardRequestCount(mockFetch)).toBe(1);
    });

    /**
     * The button unmounts the moment it is pressed, and an unmounted focused
     * element drops focus to `<body>` — returning a keyboard user to the top of
     * the document to re-traverse the page for the rows they just revealed.
     * The tasks card answers this the same way, and for the same reason.
     */
    it('hands focus to the first revealed row rather than dropping it', async () => {
      serveReady(FIVE_DATES);
      const user = userEvent.setup();

      renderWithProviders(<UpcomingDatesCard />);
      await user.click(
        await screen.findByRole('button', { name: /show all/i })
      );

      const revealed =
        within(datesList()).getAllByRole('listitem')[VISIBLE_UPCOMING_DATES];
      await waitFor(() =>
        expect(revealed).toContainElement(document.activeElement as HTMLElement)
      );
      expect(document.activeElement).not.toBe(document.body);
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

    /**
     * The shapes belong to `DashboardSectionPlaceholder` and are asserted
     * there; what belongs here is that *this* card reaches them.
     */
    it('draws the skeleton and the W29 unavailable line (ITER18-004 Phase 16)', async () => {
      routeFetch(() => new Promise<Response>(() => {}));

      const { unmount } = renderWithProviders(<UpcomingDatesCard />);

      const loading = screen.getByTestId('upcoming-dates-loading');
      expect(loading).toHaveAttribute('aria-busy', 'true');
      expect(
        loading.querySelectorAll(
          '[data-testid="dashboard-section-skeleton-row"]'
        ).length
      ).toBeGreaterThan(0);
      unmount();

      serveSection({ status: DashboardSectionStatus.UNAVAILABLE, data: null });
      renderWithProviders(<UpcomingDatesCard />);

      const unavailable = await screen.findByTestId(
        'upcoming-dates-unavailable'
      );
      expect(unavailable.querySelector('svg')).toHaveAttribute(
        'aria-hidden',
        'true'
      );
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
