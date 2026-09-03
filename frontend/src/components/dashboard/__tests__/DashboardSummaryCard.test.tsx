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

import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';
import { renderWithProviders } from '@/test-utils';
import { DashboardSummaryCard, localDateIn } from '../DashboardSummaryCard';
import {
  DashboardSectionStatus,
  DashboardSummaryState,
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
 * The day every test renders against: **today in the fixture's zone**.
 *
 * Not a fixed past date, which is what this was before the anchor-freshness
 * guard existed: the card now refuses to regenerate a day its anchor has
 * outlived (see `isStillToday`), so a hard-coded past day would disable the
 * control in every test rather than in the one test that is about it. The
 * stale case gets its own anchor below and needs no clock mocking — a day in
 * 2020 is stale by construction.
 */
const ANCHOR_DATE = localDateIn(ANCHOR_TIMEZONE, new Date());
const REGENERATE_URL = `/api/journals/daily-summary/${ANCHOR_DATE}/regenerate`;

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
        agenda: { status: DashboardSectionStatus.READY, data: { entries: [] } },
        tasks: { status: DashboardSectionStatus.READY, data: {} },
        upcoming_dates: { status: DashboardSectionStatus.READY, data: {} },
      },
    },
    meta: { anchor: { date: ANCHOR_DATE, timezone: ANCHOR_TIMEZONE } },
  };
}

interface RouteHandlers {
  readonly dashboard: () => Promise<Response>;
  readonly regenerate?: () => Promise<Response>;
}

/**
 * Route `fetch` by URL: the dashboard and the regenerate endpoint get their own
 * handlers, and everything else — the `AuthProvider`'s session check — gets an
 * authenticated user.
 */
function routeFetch({ dashboard, regenerate }: RouteHandlers) {
  mockFetch.mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url === DASHBOARD_URL) {
      return dashboard();
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

/** Render the card and wait for it to be on screen. */
async function renderCard(): Promise<HTMLElement> {
  renderWithProviders(<DashboardSummaryCard />);
  return screen.findByTestId('dashboard-summary-card');
}

function regenerateButton(): HTMLElement {
  return screen.getByRole('button', { name: /regenerate/i });
}

/**
 * The day-in-zone helper, asserted against dates written out by hand.
 *
 * The card's fixtures use this helper too, so they cannot catch it being
 * wrong — these can. `format` was the first implementation and is what these
 * pin against: which separator a locale renders is CLDR data rather than a
 * guarantee, so a build whose `en-CA` used slashes would have disabled
 * Regenerate on a current anchor. Assembling the parts is locale-independent.
 */
describe('localDateIn', () => {
  it('renders the day in the given zone as YYYY-MM-DD', () => {
    // 06:00 UTC on 29 July is 16:00 the same day in Sydney.
    expect(
      localDateIn('Australia/Sydney', new Date('2026-07-29T06:00:00Z'))
    ).toBe('2026-07-29');
  });

  it('gives the local day, not the UTC one, either side of midnight', () => {
    const instant = new Date('2026-07-29T20:00:00Z');

    // 06:00 on the 30th in Sydney; still 16:00 on the 29th in New York.
    expect(localDateIn('Australia/Sydney', instant)).toBe('2026-07-30');
    expect(localDateIn('America/New_York', instant)).toBe('2026-07-29');
  });

  it('zero-pads single-digit months and days', () => {
    expect(localDateIn('UTC', new Date('2026-01-05T12:00:00Z'))).toBe(
      '2026-01-05'
    );
  });
});

describe('DashboardSummaryCard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    servingDashboard(dashboardWith(GENERATED_SUMMARY));
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

      jest.useFakeTimers();
      try {
        jest.setSystemTime(new Date(Date.now() + 2 * 24 * 60 * 60 * 1000));

        // Still enabled — nothing has re-rendered, which is the whole point.
        expect(regenerateButton()).toBeEnabled();
        fireEvent.click(regenerateButton());
      } finally {
        jest.useRealTimers();
      }

      expect(
        mockFetch.mock.calls.filter(
          ([input]) => String(input) === REGENERATE_URL
        )
      ).toHaveLength(0);
    });

    /**
     * A zone the browser cannot parse throws inside `Intl`. The server
     * resolved this day and the browser cannot second-guess which one it
     * meant, so the anchor is trusted rather than the control being disabled
     * for a reason the reader could never resolve.
     */
    it('trusts the anchor when its zone means nothing to the browser', async () => {
      servingDashboard({
        ...dashboardWith(GENERATED_SUMMARY),
        meta: { anchor: { date: ANCHOR_DATE, timezone: 'Nowhere/Nothing' } },
      });

      await renderCard();
      await screen.findByTestId('dashboard-summary-text');

      expect(regenerateButton()).toBeEnabled();
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
     * The generating state is the one a user can otherwise be stuck in:
     * nothing currently moves a journal daily summary out of `pending`, so the
     * control that resolves it must not be the one the state disables.
     */
    it('stays enabled while the summary reports itself generating', async () => {
      servingDashboard(dashboardWith(GENERATING_SUMMARY));

      await renderCard();

      await screen.findByText(GENERATING_LINE);
      expect(regenerateButton()).toBeEnabled();
    });

    it('is disabled until the anchor day it would post to is known', async () => {
      routeFetch({ dashboard: () => new Promise<Response>(() => {}) });

      await renderCard();

      expect(regenerateButton()).toBeDisabled();
    });

    it("posts to the server's anchor day and shows the refreshed summary", async () => {
      const user = userEvent.setup();
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
      const user = userEvent.setup();

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
      const user = userEvent.setup();

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
