/**
 * @jest-environment jsdom
 *
 * The agenda card (**W11**–**W18**, wireframe gap 1): today's event journals,
 * read from the dashboard payload the page already fetched.
 *
 * Rendered over the **real** `useHomeDashboard` hook against a routed `fetch`
 * mock rather than a mocked hook, as the summary card's tests are: what the
 * card shows is derived from the section envelope — ready with entries, ready
 * and empty, unavailable — and a card that ignored `status` or re-sorted the
 * server's list would pass against a mocked hook.
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test-utils';
import { AgendaCard } from '../AgendaCard';
import { DashboardSectionStatus } from '@/lib/api/home-dashboard';
import type {
  HomeDashboardAgenda,
  HomeDashboardAgendaEntry,
  HomeDashboardResponse,
} from '@/lib/api/home-dashboard';

// jest.setup.ts mocks @/lib/constants but omits the home-dashboard endpoint;
// use the real constants rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

const DASHBOARD_URL = '/api/home-dashboard';
const EMPTY_LINE = 'Nothing scheduled today.';
const LIST_NAME = "Today's agenda";
/** The server's local tomorrow. A Saturday, which the row's label works out. */
const TOMORROW_DATE = '2026-08-01';
const TOMORROW_LIST_NAME = "Tomorrow's agenda";

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const AUTHENTICATED_SESSION = {
  authenticated: true,
  user: { id: '1', email: 'test@example.com', name: 'Test User' },
};

function entry(
  overrides: Partial<HomeDashboardAgendaEntry> & { journal_id: number }
): HomeDashboardAgendaEntry {
  return {
    title: `Event ${overrides.journal_id}`,
    is_all_day: false,
    starts_at: '2026-07-31T09:00:00+10:00',
    ends_at: '2026-07-31T10:00:00+10:00',
    start_time: '09:00:00',
    end_time: '10:00:00',
    timezone: 'Australia/Sydney',
    location: null,
    calendar_color: '#336699',
    is_cancelled: false,
    tags: [],
    participants: [],
    ...overrides,
  };
}

/** The order the server sends: all-day first, then timed ascending. */
const HOLIDAY = entry({
  journal_id: 1,
  title: 'Public holiday',
  is_all_day: true,
  start_time: null,
  end_time: null,
});
const STANDUP = entry({
  journal_id: 2,
  title: 'Standup',
  start_time: '09:00:00',
  end_time: '09:15:00',
});
const LUNCH = entry({
  journal_id: 3,
  title: 'Lunch with Sam',
  start_time: '12:30:00',
  end_time: '13:30:00',
  location: 'The cafe',
  is_cancelled: true,
});

/** Tomorrow's entries, in the server's order. */
const TOMORROW_STANDUP = entry({
  journal_id: 4,
  title: 'Tomorrow standup',
  starts_at: '2026-08-01T09:00:00+10:00',
  ends_at: '2026-08-01T09:15:00+10:00',
  start_time: '09:00:00',
  end_time: '09:15:00',
});
const TOMORROW_RETRO = entry({
  journal_id: 5,
  title: 'Tomorrow retro',
  starts_at: '2026-08-01T16:00:00+10:00',
  ends_at: '2026-08-01T17:00:00+10:00',
  start_time: '16:00:00',
  end_time: '17:00:00',
});

function dashboardDocument(
  agenda: HomeDashboardResponse['data']['attributes']['agenda']
): HomeDashboardResponse {
  return {
    data: {
      type: 'home-dashboards',
      id: 'user-1',
      attributes: {
        summary: { status: DashboardSectionStatus.UNAVAILABLE, data: null },
        agenda,
        tasks: { status: DashboardSectionStatus.READY, data: {} },
        upcoming_dates: { status: DashboardSectionStatus.READY, data: {} },
      },
    },
    meta: { anchor: { date: '2026-07-31', timezone: 'Australia/Sydney' } },
  };
}

function agendaWith(
  entries: HomeDashboardAgendaEntry[],
  tomorrow: HomeDashboardAgendaEntry[] = []
): HomeDashboardAgenda {
  return { entries, tomorrow: { date: TOMORROW_DATE, entries: tomorrow } };
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

function serveAgenda(
  agenda: HomeDashboardResponse['data']['attributes']['agenda']
) {
  routeFetch(() =>
    Promise.resolve({
      ok: true,
      json: async () => dashboardDocument(agenda),
    } as Response)
  );
}

function serveReady(
  entries: HomeDashboardAgendaEntry[],
  tomorrow: HomeDashboardAgendaEntry[] = []
) {
  serveAgenda({
    status: DashboardSectionStatus.READY,
    data: agendaWith(entries, tomorrow),
  });
}

function agendaList() {
  return screen.getByRole('list', { name: LIST_NAME });
}

describe('AgendaCard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  describe('with entries today', () => {
    it('renders them inside the list labelled "Today\'s agenda"', async () => {
      serveReady([HOLIDAY, STANDUP, LUNCH]);

      renderWithProviders(<AgendaCard />);

      const rows = await within(agendaList()).findAllByRole('listitem');
      expect(rows).toHaveLength(3);
    });

    it("renders them in the server's order and does not re-sort", async () => {
      // The all-day-first / ascending rule lives in one place — the backend
      // (Phase 5a) — and is pinned there. The card must draw the list it is
      // given: served deliberately in the order the wireframe wants, so a card
      // that sorted by some other key (title, say) would fail this.
      serveReady([HOLIDAY, STANDUP, LUNCH]);

      renderWithProviders(<AgendaCard />);

      const rows = await within(agendaList()).findAllByRole('listitem');
      expect(
        rows.map(row => within(row).getByRole('link').textContent)
      ).toEqual(['Public holiday', 'Standup', 'Lunch with Sam']);
    });

    it('draws each entry through the entry row, cancelled ones marked', async () => {
      serveReady([HOLIDAY, STANDUP, LUNCH]);

      renderWithProviders(<AgendaCard />);

      const lunch = await screen.findByTestId('agenda-entry-3');
      expect(within(lunch).getByTestId('agenda-entry-cancelled')).toBeVisible();
      expect(within(lunch).getByTestId('agenda-entry-time')).toHaveTextContent(
        '12:30 – 13:30'
      );
      expect(
        within(screen.getByTestId('agenda-entry-1')).getByTestId(
          'agenda-entry-all-day'
        )
      ).toBeInTheDocument();
      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
    });

    it('links each title to its journal', async () => {
      serveReady([STANDUP]);

      renderWithProviders(<AgendaCard />);

      expect(
        await screen.findByRole('link', { name: 'Standup' })
      ).toHaveAttribute('href', '/journals/2');
    });
  });

  describe('with nothing scheduled today (gap 1, W29 idiom)', () => {
    it('says so in a single line and draws no rows', async () => {
      serveReady([]);

      renderWithProviders(<AgendaCard />);

      expect(await screen.findByText(EMPTY_LINE)).toBeInTheDocument();
      expect(within(agendaList()).queryAllByRole('listitem')).toHaveLength(0);
      // No error styling, no retry: this is a good outcome, not a failure.
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });

  describe('while the dashboard is still loading', () => {
    it('shows a loading line rather than claiming nothing is scheduled', () => {
      routeFetch(() => new Promise<Response>(() => {}));

      renderWithProviders(<AgendaCard />);

      expect(screen.getByTestId('agenda-loading')).toHaveTextContent(
        /loading/i
      );
      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
      expect(agendaList()).toBeInTheDocument();
    });
  });

  describe('when the section is unavailable', () => {
    it('says the agenda is unavailable, not that nothing is scheduled', async () => {
      serveAgenda({ status: DashboardSectionStatus.UNAVAILABLE, data: null });

      renderWithProviders(<AgendaCard />);

      expect(await screen.findByTestId('agenda-unavailable')).toHaveTextContent(
        /unavailable/i
      );
      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
      expect(within(agendaList()).queryAllByRole('listitem')).toHaveLength(0);
    });

    it('degrades to the same line when the whole request fails', async () => {
      routeFetch(() =>
        Promise.resolve({
          ok: false,
          json: async () => ({ errors: [{ detail: 'Session expired' }] }),
        } as Response)
      );

      renderWithProviders(<AgendaCard />);

      expect(await screen.findByTestId('agenda-unavailable')).toBeVisible();
      expect(screen.queryByText(EMPTY_LINE)).not.toBeInTheDocument();
    });
  });

  /**
   * The disclosure is the card's, not the shell's: it is drawn from the
   * payload's own `tomorrow` day, and only once the section is ready — a
   * control counting "0 events" over a section that has not answered would be
   * a claim the card cannot make.
   */
  describe('tomorrow beneath today (W19, W20)', () => {
    it('draws the disclosure from the payload’s tomorrow, shut', async () => {
      serveReady([STANDUP], [TOMORROW_STANDUP, TOMORROW_RETRO]);

      renderWithProviders(<AgendaCard />);

      const trigger = await screen.findByTestId('tomorrow-trigger');
      expect(trigger).toHaveAttribute('aria-expanded', 'false');
      expect(screen.getByTestId('tomorrow-label')).toHaveTextContent(
        'Tomorrow — Saturday, 1 August'
      );
      expect(screen.getByTestId('tomorrow-count')).toHaveTextContent(
        '2 events'
      );
    });

    it('expands in place, leaving today’s list where it was', async () => {
      const user = userEvent.setup();
      serveReady([STANDUP], [TOMORROW_STANDUP]);

      renderWithProviders(<AgendaCard />);

      await user.click(await screen.findByTestId('tomorrow-trigger'));

      // Tomorrow arrives...
      expect(
        within(
          screen.getByRole('list', { name: TOMORROW_LIST_NAME })
        ).getByRole('link', { name: 'Tomorrow standup' })
      ).toBeInTheDocument();
      // ...and today has not gone anywhere. "In place" is the whole point.
      expect(
        within(agendaList()).getByRole('link', { name: 'Standup' })
      ).toBeInTheDocument();
    });

    it('offers the disclosure even when nothing is on today', async () => {
      serveReady([], [TOMORROW_STANDUP]);

      renderWithProviders(<AgendaCard />);

      expect(await screen.findByText(EMPTY_LINE)).toBeInTheDocument();
      expect(screen.getByTestId('tomorrow-count')).toHaveTextContent('1 event');
    });

    it('draws none while the dashboard is still loading', () => {
      routeFetch(() => new Promise<Response>(() => {}));

      renderWithProviders(<AgendaCard />);

      expect(screen.getByTestId('agenda-loading')).toBeInTheDocument();
      expect(screen.queryByTestId('tomorrow-trigger')).not.toBeInTheDocument();
    });

    /**
     * Found by the e2e, not by design: a ready agenda whose `tomorrow` was
     * missing threw out of render and blanked the **entire page** — summary,
     * tasks and dates with it. The type says the field is always there, and
     * the server does send it; this is the section-independence rule the
     * specification states, held against a payload that breaks its own
     * contract rather than only against one that says `unavailable`.
     */
    it('keeps today drawn when a ready agenda arrives without a tomorrow', async () => {
      serveAgenda({
        status: DashboardSectionStatus.READY,
        data: { entries: [STANDUP] } as unknown as HomeDashboardAgenda,
      });

      renderWithProviders(<AgendaCard />);

      expect(
        await within(agendaList()).findByRole('link', { name: 'Standup' })
      ).toBeInTheDocument();
      expect(screen.queryByTestId('tomorrow-trigger')).not.toBeInTheDocument();
    });

    /**
     * The same failure one step further in: a `tomorrow` that is there but
     * carries no list. From the disclosure's seat this is indistinguishable
     * from the case above — it reads `entries.length` either way — so the
     * guard is on the shape, not on the key.
     */
    it('keeps today drawn when tomorrow arrives with no entries list', async () => {
      serveAgenda({
        status: DashboardSectionStatus.READY,
        data: {
          entries: [STANDUP],
          tomorrow: { date: TOMORROW_DATE },
        } as unknown as HomeDashboardAgenda,
      });

      renderWithProviders(<AgendaCard />);

      expect(
        await within(agendaList()).findByRole('link', { name: 'Standup' })
      ).toBeInTheDocument();
      expect(screen.queryByTestId('tomorrow-trigger')).not.toBeInTheDocument();
    });

    it('draws none when the section is unavailable', async () => {
      serveAgenda({ status: DashboardSectionStatus.UNAVAILABLE, data: null });

      renderWithProviders(<AgendaCard />);

      await screen.findByTestId('agenda-unavailable');
      expect(screen.queryByTestId('tomorrow-trigger')).not.toBeInTheDocument();
    });
  });

  describe('the card frame (W11)', () => {
    it('carries its wireframe title and description in every state', async () => {
      serveReady([]);

      renderWithProviders(<AgendaCard />);

      expect(
        screen.getByRole('heading', { level: 3, name: 'Agenda' })
      ).toBeInTheDocument();
      expect(
        screen.getByText("Today's schedule in time order, all-day items first.")
      ).toBeInTheDocument();
      await screen.findByText(EMPTY_LINE);
    });

    it('marks its decorative icons as hidden from assistive tech', async () => {
      serveReady([STANDUP]);

      const { container } = renderWithProviders(<AgendaCard />);
      await screen.findByRole('link', { name: 'Standup' });

      const icons = container.querySelectorAll('svg');
      expect(icons.length).toBeGreaterThan(0);
      icons.forEach(icon => {
        expect(icon).toHaveAttribute('aria-hidden', 'true');
      });
    });
  });
});
