/**
 * @jest-environment jsdom
 *
 * The dashboard's headline: today's AI daily summary (**W5**–**W10**).
 *
 * These tests render the card over the **real** `useHomeDashboard` hook against
 * a routed `fetch` mock rather than a mocked hook, for the same reason the page
 * shell's tests do: the card's three states are derived from the section
 * envelope the server sends. Mocking the hook would let a card that ignores
 * the section's `status` pass. **W6**'s Regenerate action, and the tests that
 * drive it, land in Phase 4c.
 */

import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '@/test-utils';
import { DashboardSummaryCard } from '../DashboardSummaryCard';
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

const DASHBOARD_URL = '/api/home-dashboard';

/** The day every test renders against — fixed, and in the past. */
const ANCHOR_DATE = '2026-07-29';

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
    meta: { anchor: { date: ANCHOR_DATE, timezone: 'Australia/Sydney' } },
  };
}

interface RouteHandlers {
  readonly dashboard: () => Promise<Response>;
}

/**
 * Route `fetch` by URL: the dashboard gets its own handler, and everything
 * else — the `AuthProvider`'s session check — gets an authenticated user.
 */
function routeFetch({ dashboard }: RouteHandlers) {
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
});
