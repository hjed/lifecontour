/**
 * @jest-environment jsdom
 *
 * The dashboard's headline: today's AI daily summary (**W5**–**W10**).
 *
 * These tests render the card over the **real** `useHomeDashboard` hook against
 * a routed `fetch` mock rather than a mocked hook, for the same reason the page
 * shell's tests do: the card's three states are derived from the section
 * envelope the server sends, and the Regenerate action posts to the day the
 * server anchored the page on. Mocking the hook would let a card that reads the
 * browser's clock, or that ignores the section's `status`, pass.
 */

import { QueryClient, useQueryClient } from '@tanstack/react-query';
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { useEffect } from 'react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { renderWithProviders } from '@/test-utils';
import { DashboardSummaryCard } from '../DashboardSummaryCard';
import { todayIn } from '@/lib/date-utils';
import {
  DashboardSectionStatus,
  DashboardSummaryState,
  homeDashboardKeys,
} from '@/lib/api/home-dashboard';
import type {
  HomeDashboardResponse,
  HomeDashboardSummary,
} from '@/lib/api/home-dashboard';

// jest.setup.ts mocks @/lib/constants but omits the home-dashboard endpoint;
// use the real constants rather than re-declaring the whole mock.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
  },
}));

const DASHBOARD_URL = '/api/home-dashboard';

const ANCHOR_TIMEZONE = 'Australia/Sydney';

/**
 * The instant every test runs at: 13:00 in Sydney on 31 July 2026.
 *
 * Frozen for the whole suite (see the top-level `beforeEach`), because the card
 * reads the clock itself — at render, and again inside the click handler — and
 * the expectations here are built from a "today" sampled separately. On a live
 * clock the two readings can straddle midnight, and an "enabled" assertion then
 * fails for a reason that has nothing to do with the card: Augment's review of
 * PR #1447 found it in the unrecognised-zone pair, and `ANCHOR_DATE`, sampled
 * at import, had the same exposure across the whole suite. Midday keeps the
 * boundary eleven hours off, so nothing a test waits on can reach it.
 */
const NOW = new Date('2026-07-31T03:00:00Z');

/**
 * The day every test renders against: **today in the fixture's zone**.
 *
 * Not a fixed past date, which is what this was before the anchor-freshness
 * guard existed: the card now refuses to regenerate a day its anchor has
 * outlived (see `isAnchorStillToday`), so a hard-coded past day would disable the
 * control in every test rather than in the one test that is about it. The
 * stale case gets its own anchor below and needs no clock mocking — a day in
 * 2020 is stale by construction.
 */
const ANCHOR_DATE = todayIn(ANCHOR_TIMEZONE, NOW);
const SUMMARY_URL = `/api/journals/daily-summary/${ANCHOR_DATE}`;
const REGENERATE_URL = `${SUMMARY_URL}/regenerate`;

const UNAVAILABLE_LINE = /no summary today/i;
const GENERATING_LINE = 'Summary is being generated...';

const GENERATED_SUMMARY: HomeDashboardSummary = {
  state: DashboardSummaryState.GENERATED,
  summary_text: 'A quiet Wednesday. Two journals, one long walk.',
  journal_count: 3,
  event_count: 2,
  contact_count: 4,
  mood_average: 7.5,
};

const GENERATING_SUMMARY: HomeDashboardSummary = {
  state: DashboardSummaryState.GENERATING,
  summary_text: null,
  journal_count: 3,
  event_count: 2,
  contact_count: 4,
  mood_average: 7.5,
};

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

const AUTHENTICATED_SESSION = {
  authenticated: true,
  user: { id: '1', email: 'test@example.com', name: 'Test User' },
};

/** A dashboard document whose summary section holds the given payload. */
function dashboardWith(summary: HomeDashboardSummary): HomeDashboardResponse {
  return dashboardDocument({
    status: DashboardSectionStatus.READY,
    data: summary,
  });
}

/** A dashboard document whose summary section reports it has nothing. */
function dashboardWithoutSummary(): HomeDashboardResponse {
  return dashboardDocument({
    status: DashboardSectionStatus.UNAVAILABLE,
    data: null,
  });
}

function dashboardDocument(
  summary: HomeDashboardResponse['data']['attributes']['summary']
): HomeDashboardResponse {
  return {
    data: {
      type: 'home-dashboards',
      id: 'user-1',
      attributes: {
        summary,
        agenda: {
          status: DashboardSectionStatus.READY,
          data: { entries: [], tomorrow: { date: '2026-07-30', entries: [] } },
        },
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
        upcoming_dates: {
          status: DashboardSectionStatus.UNAVAILABLE,
          data: null,
        },
      },
    },
    meta: { anchor: { date: ANCHOR_DATE, timezone: ANCHOR_TIMEZONE } },
  };
}

interface RouteHandlers {
  readonly dashboard: () => Promise<Response>;
  readonly regenerate?: () => Promise<Response>;
  /** The summary read the card makes on load; unconfigured by default. */
  readonly summary?: () => Promise<Response>;
}

/**
 * Route `fetch` by URL: the dashboard and the regenerate endpoint get their own
 * handlers, and everything else — the `AuthProvider`'s session check — gets an
 * authenticated user.
 */
function routeFetch({ dashboard, regenerate, summary }: RouteHandlers) {
  mockFetch.mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url === DASHBOARD_URL) {
      return dashboard();
    }
    if (url === SUMMARY_URL) {
      return summary ? summary() : jsonResponse({ data: null });
    }
    if (url === REGENERATE_URL && regenerate) {
      return regenerate();
    }
    return Promise.resolve({
      ok: true,
      json: async () => AUTHENTICATED_SESSION,
    } as Response);
  });
}

function jsonResponse(body: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, json: async () => body } as Response);
}

/** Serve one fixed dashboard document for the life of the test. */
function servingDashboard(document: HomeDashboardResponse) {
  routeFetch({ dashboard: () => jsonResponse(document) });
}

/** `userEvent` waits on timers, so it has to drive the frozen clock itself. */
function userOnTheFrozenClock() {
  return userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
}

/** Render the card and wait for it to be on screen. */
async function renderCard(): Promise<HTMLElement> {
  renderWithProviders(<DashboardSummaryCard />);
  return screen.findByTestId('dashboard-summary-card');
}

function regenerateButton(): HTMLElement {
  return screen.getByRole('button', { name: /regenerate/i });
}

describe('DashboardSummaryCard', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(NOW);
    jest.clearAllMocks();
    mockFetch.mockReset();
    servingDashboard(dashboardWith(GENERATED_SUMMARY));
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('The card itself (W5, W6)', () => {
    it('is a labelled region headed "AI Daily Summary"', async () => {
      await renderCard();

      expect(
        screen.getByRole('heading', { level: 2, name: 'AI Daily Summary' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('region', { name: 'AI Daily Summary' })
      ).toBeInTheDocument();
    });

    it('is distinguished from the evidence cards by a primary accent bar', async () => {
      const card = await renderCard();

      expect(card).toHaveClass(
        'bg-primary/5',
        'border-primary/20',
        'border-l-4',
        'border-l-primary'
      );
    });

    it('carries the sparkle chip beside the label, hidden from assistive tech', async () => {
      const card = await renderCard();

      // W6 draws the icon in a rounded primary-tinted chip. It says nothing the
      // heading beside it does not, so it must not be announced.
      const icon = card.querySelector('svg.lucide-sparkles');
      expect(icon).not.toBeNull();
      expect(icon).toHaveAttribute('aria-hidden', 'true');
      expect(icon?.parentElement).toHaveClass('bg-primary/10', 'rounded-md');
    });

    /**
     * The negative is the assertion worth having. A live region here looks
     * like care and is the opposite: the body's *first* content change is
     * "loading" giving way to the summary, so on a page every sign-in lands on
     * a screen-reader user would have the whole AI summary read at them
     * unbidden. The change actually worth announcing — the regeneration they
     * asked for — already announces itself through the toast.
     */
    it('does not turn the body into a live region', async () => {
      const card = await renderCard();
      await screen.findByTestId('dashboard-summary-text');

      expect(card.querySelectorAll('[aria-live]')).toHaveLength(0);
    });

    it('shows a quiet line while the page query is still in flight', async () => {
      routeFetch({ dashboard: () => new Promise<Response>(() => {}) });

      await renderCard();

      expect(screen.getByTestId('dashboard-summary-loading')).toHaveTextContent(
        "Loading today's summary..."
      );
      // ITER18-004 Phase 16 draws that sentence as bars in the shape of the
      // prose that is coming (W7), with the sentence itself kept for a reader
      // who cannot see them. Busy rather than live, for the reason this card
      // refused `aria-live` on its body in Phase 4.
      expect(screen.getByTestId('dashboard-summary-loading')).toHaveAttribute(
        'aria-busy',
        'true'
      );
      expect(
        screen
          .getByTestId('dashboard-summary-loading')
          .querySelectorAll('[data-slot="skeleton"]').length
      ).toBeGreaterThan(0);
    });
  });

  describe('Generated (W7)', () => {
    it('renders the summary prose in full', async () => {
      await renderCard();

      expect(
        await screen.findByTestId('dashboard-summary-text')
      ).toHaveTextContent(GENERATED_SUMMARY.summary_text!);
    });

    it('does not clamp or truncate the prose', async () => {
      await renderCard();

      const prose = await screen.findByTestId('dashboard-summary-text');
      expect(prose.outerHTML).not.toMatch(/line-clamp|truncate/);
    });

    /**
     * **W7** asks for "one or more prose **paragraphs**". A blank line in the
     * model's output has to become a real `<p>` — that is what gives the
     * paragraphs spacing, and what lets a screen reader move between them.
     */
    it('renders a blank line in the summary as a separate paragraph', async () => {
      servingDashboard(
        dashboardWith({
          ...GENERATED_SUMMARY,
          summary_text: 'The morning was quiet.\n\nThe afternoon was not.',
        })
      );

      await renderCard();

      const prose = await screen.findByTestId('dashboard-summary-text');
      const paragraphs = Array.from(prose.querySelectorAll('p')).map(
        paragraph => paragraph.textContent
      );
      expect(paragraphs).toEqual([
        'The morning was quiet.',
        'The afternoon was not.',
      ]);
    });

    it('renders a summary with no blank line as a single paragraph', async () => {
      await renderCard();

      const prose = await screen.findByTestId('dashboard-summary-text');
      expect(prose.querySelectorAll('p')).toHaveLength(1);
    });

    it('offers no edit affordance anywhere on the card', async () => {
      const card = await renderCard();

      await screen.findByTestId('dashboard-summary-text');
      expect(card.querySelectorAll('input, textarea')).toHaveLength(0);
      expect(
        within(card).queryByRole('button', { name: /edit/i })
      ).not.toBeInTheDocument();
    });

    it('shows no "Generating..." badge', async () => {
      await renderCard();

      await screen.findByTestId('dashboard-summary-text');
      expect(screen.queryByText('Generating...')).not.toBeInTheDocument();
    });
  });

  describe('Generating (W8)', () => {
    beforeEach(() => {
      servingDashboard(dashboardWith(GENERATING_SUMMARY));
    });

    it('shows the "Generating..." badge beside the header label', async () => {
      await renderCard();

      expect(await screen.findByText('Generating...')).toBeInTheDocument();
    });

    it('replaces the body with a single muted line', async () => {
      await renderCard();

      expect(await screen.findByText(GENERATING_LINE)).toBeInTheDocument();
      expect(
        screen.queryByTestId('dashboard-summary-text')
      ).not.toBeInTheDocument();
    });
  });

  describe('Unavailable (W9)', () => {
    beforeEach(() => {
      servingDashboard(dashboardWithoutSummary());
    });

    it('says so in one quiet line that reassures the rest of the page works', async () => {
      await renderCard();

      const line = await screen.findByTestId('dashboard-summary-unavailable');
      expect(line).toHaveTextContent(UNAVAILABLE_LINE);
      expect(line).toHaveTextContent(/everything below still works/i);
      expect(line).toHaveClass('text-muted-foreground');
    });

    it('renders no error styling and no retry banner', async () => {
      const card = await renderCard();

      const line = await screen.findByTestId('dashboard-summary-unavailable');
      expect(card.className).not.toMatch(/destructive/);
      expect(line.className).not.toMatch(/destructive/);
      // Any alert at all, not one whose name says "error": W9 forbids the
      // banner, and a banner that called itself something else would still be
      // one.
      expect(within(card).queryAllByRole('alert')).toHaveLength(0);
    });

    it('renders the same quiet line when the dashboard request fails outright', async () => {
      routeFetch({
        dashboard: () =>
          Promise.resolve({
            ok: false,
            json: async () => ({ errors: [{ detail: 'Session expired' }] }),
          } as Response),
      });

      await renderCard();

      expect(
        await screen.findByTestId('dashboard-summary-unavailable')
      ).toBeInTheDocument();
    });

    /**
     * The one place the control is offered and cannot be used, pinned so it
     * cannot change unnoticed: a failed *request* carries no anchor, and the
     * day to regenerate is the server's today in the user's configured zone —
     * posting the browser's would regenerate the wrong day for anyone whose
     * zone differs. Recovering the request is a retry, which is Phase 16's.
     */
    it('cannot offer a usable Regenerate when the request itself failed', async () => {
      routeFetch({
        dashboard: () =>
          Promise.resolve({
            ok: false,
            json: async () => ({ errors: [{ detail: 'Session expired' }] }),
          } as Response),
      });

      await renderCard();

      await screen.findByTestId('dashboard-summary-unavailable');
      expect(regenerateButton()).toBeInTheDocument();
      expect(regenerateButton()).toBeDisabled();
    });
  });

  describe('Key stats footer (W10)', () => {
    it('renders in the generated state', async () => {
      await renderCard();

      const stats = await screen.findByTestId('dashboard-summary-stats');
      expect(within(stats).getByText('Journals')).toBeInTheDocument();
      expect(within(stats).getByText('Events')).toBeInTheDocument();
      expect(within(stats).getByText('Contacts')).toBeInTheDocument();
      expect(within(stats).getByText('Avg Mood')).toBeInTheDocument();
      expect(within(stats).getByText('7.5/10')).toBeInTheDocument();
    });

    it('is absent in the generating state', async () => {
      servingDashboard(dashboardWith(GENERATING_SUMMARY));

      await renderCard();

      await screen.findByText(GENERATING_LINE);
      expect(
        screen.queryByTestId('dashboard-summary-stats')
      ).not.toBeInTheDocument();
    });

    it('is absent in the unavailable state', async () => {
      servingDashboard(dashboardWithoutSummary());

      await renderCard();

      await screen.findByTestId('dashboard-summary-unavailable');
      expect(
        screen.queryByTestId('dashboard-summary-stats')
      ).not.toBeInTheDocument();
    });
  });

  describe('Regenerate (W6)', () => {
    /**
     * A dashboard held open across local midnight keeps yesterday's anchor —
     * the query has one fixed key, a five-minute `staleTime` and no refetch
     * scheduled at the day boundary (Phase 3's follow-up 2, owned by Phase
     * 16). A *label* that is a day out is Phase 16's to fix; a **write** keyed
     * on it is this phase's, because regenerating would rewrite the wrong
     * day's summary under a page headed "Today".
     */
    it('will not regenerate a day the anchor has outlived', async () => {
      servingDashboard({
        ...dashboardWith(GENERATED_SUMMARY),
        meta: { anchor: { date: '2020-01-01', timezone: ANCHOR_TIMEZONE } },
      });

      await renderCard();
      await screen.findByTestId('dashboard-summary-text');

      expect(regenerateButton()).toBeDisabled();
    });

    /**
     * The render-time check is the *affordance*; it is not the guard.
     *
     * The disabled state is computed while React renders, and a dashboard left
     * mounted across local midnight need never render again — nothing on this
     * page ticks. So the button stays enabled while its anchor quietly goes
     * stale, and only a re-check inside the click handler stops the write. The
     * clock moves here *after* the render, deliberately, so the button is still
     * enabled when it is pressed: a version that only checked at render time
     * would post yesterday's date and fail this test.
     */
    it('declines to post once the day has turned under a mounted card', async () => {
      await renderCard();
      await screen.findByTestId('dashboard-summary-text');
      expect(regenerateButton()).toBeEnabled();

      // Two days on, with no render in between: nothing on this page ticks.
      jest.setSystemTime(new Date(NOW.getTime() + 2 * 24 * 60 * 60 * 1000));

      // Still enabled — nothing has re-rendered, which is the whole point.
      expect(regenerateButton()).toBeEnabled();
      fireEvent.click(regenerateButton());

      expect(
        mockFetch.mock.calls.filter(
          ([input]) => String(input) === REGENERATE_URL
        )
      ).toHaveLength(0);
    });

    /**
     * **Decided in ITER18-004 Phase 18: the zone is always resolved.** A zone
     * the browser cannot parse used to be caught here and the anchor trusted;
     * it now resolves through `date-utils`' fallback to the browser's own zone,
     * the one answer every other caller of `localDateIn` gets. The pair is what
     * pins the card's answer rather than the helper's: an anchor on the
     * browser's own date is offered and posted, and an anchor in 2020 — today
     * in no zone — is not, which the trusting version would have enabled.
     *
     * The browser's date is read from `Date`'s local getters, so both cases
     * hold whatever zone the test runner happens to be in — and from the
     * suite's frozen clock, so it is the same instant the card reads.
     */
    describe('for a zone the browser does not recognise', () => {
      const UNRECOGNISED_ZONE = 'Nowhere/Nothing';

      function browserLocalDate(instant: Date): string {
        const pad = (value: number) => String(value).padStart(2, '0');
        return `${instant.getFullYear()}-${pad(instant.getMonth() + 1)}-${pad(instant.getDate())}`;
      }

      it('reads the day in the browser’s own zone and posts it', async () => {
        const browserDay = browserLocalDate(new Date());
        const browserRegenerateUrl = `/api/journals/daily-summary/${browserDay}/regenerate`;
        const user = userOnTheFrozenClock();
        servingDashboard({
          ...dashboardWith(GENERATED_SUMMARY),
          meta: { anchor: { date: browserDay, timezone: UNRECOGNISED_ZONE } },
        });

        await renderCard();
        await screen.findByTestId('dashboard-summary-text');
        expect(regenerateButton()).toBeEnabled();

        await user.click(regenerateButton());

        await waitFor(() =>
          expect(
            mockFetch.mock.calls.filter(
              ([input]) => String(input) === browserRegenerateUrl
            )
          ).toHaveLength(1)
        );
      });

      it('does not trust an anchor the browser’s date disagrees with', async () => {
        servingDashboard({
          ...dashboardWith(GENERATED_SUMMARY),
          meta: { anchor: { date: '2020-01-01', timezone: UNRECOGNISED_ZONE } },
        });

        await renderCard();
        await screen.findByTestId('dashboard-summary-text');

        expect(regenerateButton()).toBeDisabled();
      });
    });

    it.each([
      ['generated', () => dashboardWith(GENERATED_SUMMARY)],
      ['generating', () => dashboardWith(GENERATING_SUMMARY)],
      ['unavailable', () => dashboardWithoutSummary()],
    ])('is offered in the %s state', async (_state, document) => {
      servingDashboard(document());

      await renderCard();

      await waitFor(() => expect(regenerateButton()).toBeEnabled());
    });

    /**
     * The generating state is the one a user can otherwise be stuck in: the
     * card's own read on load cannot move a summary out of `pending` when the AI
     * is unconfigured or failing, so once that read has settled the control
     * that resolves it must not be the one the state disables.
     */
    it('is usable again inside the generating state once its read on load has settled', async () => {
      servingDashboard(dashboardWith(GENERATING_SUMMARY));

      await renderCard();

      await screen.findByText(GENERATING_LINE);
      await waitFor(() => expect(regenerateButton()).toBeEnabled());
      expect(screen.getByText(GENERATING_LINE)).toBeInTheDocument();
    });

    it('is disabled until the anchor day it would post to is known', async () => {
      routeFetch({ dashboard: () => new Promise<Response>(() => {}) });

      await renderCard();

      expect(regenerateButton()).toBeDisabled();
    });

    it("posts to the server's anchor day and shows the refreshed summary", async () => {
      const user = userOnTheFrozenClock();
      let current = dashboardWith(GENERATED_SUMMARY);

      routeFetch({
        dashboard: () => jsonResponse(current),
        regenerate: () => {
          current = dashboardWith({
            ...GENERATED_SUMMARY,
            summary_text: 'A busier Wednesday after all.',
          });
          return jsonResponse({
            data: {
              type: 'journal-daily-summaries',
              id: ANCHOR_DATE,
              attributes: {
                summary_date: ANCHOR_DATE,
                summary_text: 'A busier Wednesday after all.',
                journal_count: 3,
                event_count: 2,
                contact_count: 4,
                mood_average: 7.5,
                status: 'generated',
              },
            },
          });
        },
      });

      await renderCard();
      await screen.findByTestId('dashboard-summary-text');

      await user.click(regenerateButton());

      await waitFor(() =>
        expect(
          mockFetch.mock.calls.filter(
            ([input]) => String(input) === REGENERATE_URL
          )
        ).toHaveLength(1)
      );
      const [, init] = mockFetch.mock.calls.find(
        ([input]) => String(input) === REGENERATE_URL
      )!;
      expect(init?.method).toBe('POST');

      expect(
        await screen.findByText('A busier Wednesday after all.')
      ).toBeInTheDocument();
    });

    it('marks itself busy while the regeneration is in flight', async () => {
      const user = userOnTheFrozenClock();

      routeFetch({
        dashboard: () => jsonResponse(dashboardWith(GENERATED_SUMMARY)),
        regenerate: () => new Promise<Response>(() => {}),
      });

      await renderCard();
      await screen.findByTestId('dashboard-summary-text');

      await user.click(regenerateButton());

      await waitFor(() => expect(regenerateButton()).toBeDisabled());
      expect(regenerateButton()).toHaveAttribute('aria-busy', 'true');
    });

    it('keeps the card on screen and surfaces the failure when it fails', async () => {
      const user = userOnTheFrozenClock();

      routeFetch({
        dashboard: () => jsonResponse(dashboardWith(GENERATED_SUMMARY)),
        regenerate: () =>
          Promise.resolve({
            ok: false,
            json: async () => ({
              errors: [{ detail: 'AI provider unavailable' }],
            }),
          } as Response),
      });

      await renderCard();
      await screen.findByTestId('dashboard-summary-text');

      await user.click(regenerateButton());

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith('AI provider unavailable')
      );
      expect(screen.getByTestId('dashboard-summary-text')).toHaveTextContent(
        GENERATED_SUMMARY.summary_text!
      );
      await waitFor(() => expect(regenerateButton()).toBeEnabled());
    });
  });
});

/**
 * Reach the client the providers built, so a test can make the page read the
 * dashboard again the way a task write does.
 */
function ClientProbe({
  onClient,
}: {
  readonly onClient: (client: QueryClient) => void;
}) {
  const client = useQueryClient();
  useEffect(() => onClient(client), [client, onClient]);
  return null;
}

async function renderCardWithClient(): Promise<() => QueryClient> {
  let captured: QueryClient | undefined;
  const capture = (client: QueryClient) => {
    captured = client;
  };
  renderWithProviders(
    <>
      <ClientProbe onClient={capture} />
      <DashboardSummaryCard />
    </>
  );
  await screen.findByTestId('dashboard-summary-card');
  return () => {
    expect(captured).toBeDefined();
    return captured!;
  };
}

function dashboardReads(): number {
  return mockFetch.mock.calls.filter(
    ([input]) => String(input) === DASHBOARD_URL
  ).length;
}

/**
 * ITER18-005 Phase 8: the card obtains today's summary on load, and keeps a
 * summary it has drawn for the rest of the visit.
 *
 * A task tick invalidates today's summary on the server, and the tick's own
 * refetch then reports it generating. Without the hold that refetch would take
 * the prose off the screen under a reader who only ticked a task — the
 * specification's "never regenerated underneath the user", from the other
 * side. The summary refreshes on the next load instead.
 */
describe('DashboardSummaryCard — today’s summary across a visit', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(NOW);
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('Holding a drawn summary', () => {
    it('keeps the summary and its key stats when a later read of the day reports it generating', async () => {
      let current = dashboardWith(GENERATED_SUMMARY);
      routeFetch({ dashboard: () => jsonResponse(current) });
      const client = await renderCardWithClient();
      await screen.findByTestId('dashboard-summary-text');

      current = dashboardWith(GENERATING_SUMMARY);
      await act(async () => {
        await client().invalidateQueries({ queryKey: homeDashboardKeys.all });
      });
      await waitFor(() => expect(dashboardReads()).toBe(2));

      expect(screen.getByTestId('dashboard-summary-text')).toHaveTextContent(
        GENERATED_SUMMARY.summary_text!
      );
      expect(screen.getByTestId('dashboard-summary-stats')).toBeInTheDocument();
      expect(screen.queryByText('Generating...')).not.toBeInTheDocument();
      expect(screen.queryByText(GENERATING_LINE)).not.toBeInTheDocument();
    });

    it('keeps it when a later read of the day reports no summary', async () => {
      let current = dashboardWith(GENERATED_SUMMARY);
      routeFetch({ dashboard: () => jsonResponse(current) });
      const client = await renderCardWithClient();
      await screen.findByTestId('dashboard-summary-text');

      current = dashboardWithoutSummary();
      await act(async () => {
        await client().invalidateQueries({ queryKey: homeDashboardKeys.all });
      });
      await waitFor(() => expect(dashboardReads()).toBe(2));

      expect(screen.getByTestId('dashboard-summary-text')).toHaveTextContent(
        GENERATED_SUMMARY.summary_text!
      );
      expect(screen.queryByText(UNAVAILABLE_LINE)).not.toBeInTheDocument();
    });

    it('draws a newer summary when a later read brings one', async () => {
      let current = dashboardWith(GENERATED_SUMMARY);
      routeFetch({ dashboard: () => jsonResponse(current) });
      const client = await renderCardWithClient();
      await screen.findByTestId('dashboard-summary-text');

      current = dashboardWith({
        ...GENERATED_SUMMARY,
        summary_text: 'A busier Wednesday after all.',
        journal_count: 9,
      });
      await act(async () => {
        await client().invalidateQueries({ queryKey: homeDashboardKeys.all });
      });

      expect(
        await screen.findByText('A busier Wednesday after all.')
      ).toBeInTheDocument();
      expect(
        within(screen.getByTestId('dashboard-summary-stats')).getByText('9')
      ).toBeInTheDocument();
    });

    it('lets a held summary go once the day it was drawn for has passed', async () => {
      let current = dashboardWith(GENERATED_SUMMARY);
      routeFetch({ dashboard: () => jsonResponse(current) });
      const client = await renderCardWithClient();
      await screen.findByTestId('dashboard-summary-text');

      current = dashboardWith(GENERATING_SUMMARY);
      current.meta.anchor.date = '2026-08-01';
      await act(async () => {
        await client().invalidateQueries({ queryKey: homeDashboardKeys.all });
      });

      expect(await screen.findByText(GENERATING_LINE)).toBeInTheDocument();
      expect(
        screen.queryByTestId('dashboard-summary-text')
      ).not.toBeInTheDocument();
    });
  });

  describe('Obtaining today’s summary on load', () => {
    it('marks Regenerate busy while it reads today’s summary', async () => {
      routeFetch({
        dashboard: () => jsonResponse(dashboardWith(GENERATING_SUMMARY)),
        summary: () => new Promise<Response>(() => {}),
      });

      await renderCard();
      await screen.findByText(GENERATING_LINE);

      expect(regenerateButton()).toBeDisabled();
      expect(regenerateButton()).toHaveAttribute('aria-busy', 'true');
    });

    /**
     * The first load of a new day has no row at all, which the section reports
     * as unavailable. Drawing W9's "No summary today" beside a busy Regenerate
     * for the whole of the generation would say the opposite of what is
     * happening, so while the card is obtaining one it says it is generating.
     */
    it('says it is generating, not that there is no summary, while it obtains a missing one', async () => {
      routeFetch({
        dashboard: () => jsonResponse(dashboardWithoutSummary()),
        summary: () => new Promise<Response>(() => {}),
      });

      const card = await renderCard();

      expect(await screen.findByText(GENERATING_LINE)).toBeInTheDocument();
      expect(within(card).getByText('Generating...')).toBeInTheDocument();
      expect(screen.queryByText(UNAVAILABLE_LINE)).not.toBeInTheDocument();
    });

    it('draws the summary it obtained and frees Regenerate again', async () => {
      let current = dashboardWith(GENERATING_SUMMARY);
      routeFetch({
        dashboard: () => jsonResponse(current),
        summary: () => {
          current = dashboardWith(GENERATED_SUMMARY);
          return jsonResponse({
            data: {
              type: 'journal-daily-summaries',
              id: ANCHOR_DATE,
              attributes: {
                summary_date: ANCHOR_DATE,
                summary_text: GENERATED_SUMMARY.summary_text,
                journal_count: 3,
                event_count: 2,
                contact_count: 4,
                mood_average: 7.5,
                status: 'generated',
              },
            },
          });
        },
      });

      await renderCard();

      expect(
        await screen.findByTestId('dashboard-summary-text')
      ).toHaveTextContent(GENERATED_SUMMARY.summary_text!);
      await waitFor(() => expect(regenerateButton()).toBeEnabled());
      expect(regenerateButton()).toHaveAttribute('aria-busy', 'false');
    });

    it('reads, and never posts a regeneration for itself', async () => {
      routeFetch({
        dashboard: () => jsonResponse(dashboardWith(GENERATING_SUMMARY)),
        regenerate: () => jsonResponse({ data: null }),
      });

      await renderCard();
      await waitFor(() => expect(regenerateButton()).toBeEnabled());

      const summaryCalls = mockFetch.mock.calls.filter(([input]) =>
        String(input).startsWith(SUMMARY_URL)
      );
      expect(summaryCalls.map(([input]) => String(input))).toEqual([
        SUMMARY_URL,
      ]);
    });

    it('announces nothing of its own when it obtains a summary', async () => {
      routeFetch({
        dashboard: () => jsonResponse(dashboardWith(GENERATING_SUMMARY)),
      });

      await renderCard();
      await waitFor(() => expect(regenerateButton()).toBeEnabled());

      expect(toast.success).not.toHaveBeenCalled();
      expect(toast.info).not.toHaveBeenCalled();
    });
  });
});
