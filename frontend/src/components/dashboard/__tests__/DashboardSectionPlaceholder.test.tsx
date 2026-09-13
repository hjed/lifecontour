/**
 * @jest-environment jsdom
 *
 * What a section draws while it has no list — the skeleton and the unavailable
 * treatment the wireframe does not depict (gap 9), built in the idiom of **W9**
 * and **W29** as that gap directs.
 *
 * Phases 4, 7, 12 and 14 each shipped one muted line for both, each recording
 * that the real treatment was Phase 16's. This is that treatment, and the two
 * states stay as far apart here as they were then: a reader must never take a
 * section that has not answered for a clear day.
 *
 * **The skeleton is deliberately not a live region.** Four of these mount on
 * the page every sign-in lands on, and announcing four loading sentences
 * unbidden is the noise Phase 4 refused `aria-live` on the summary body to
 * avoid. `aria-busy` plus a visually hidden sentence keeps the information for
 * a reader who goes looking without interrupting one who did not.
 */

import { render, screen } from '@testing-library/react';
import { DashboardSectionPlaceholder } from '../DashboardSectionPlaceholder';
import { DashboardSectionSkeleton } from '../DashboardSectionSkeleton';

const COPY = {
  loading: "Loading today's agenda...",
  unavailable: "Today's agenda is unavailable.",
} as const;

function renderPlaceholder(pending: boolean) {
  return render(
    <DashboardSectionPlaceholder
      pending={pending}
      copy={COPY}
      testIdPrefix='agenda'
    />
  );
}

describe('DashboardSectionSkeleton', () => {
  it('draws a run of rows in the shared row idiom', () => {
    render(
      <DashboardSectionSkeleton label='Loading' testId='agenda-loading' />
    );

    expect(
      screen.getByTestId('agenda-loading').querySelectorAll('[data-slot]')
    ).not.toHaveLength(0);
  });

  it('marks itself busy so the section reads as unfinished, not as empty', () => {
    render(
      <DashboardSectionSkeleton label='Loading' testId='agenda-loading' />
    );

    expect(screen.getByTestId('agenda-loading')).toHaveAttribute(
      'aria-busy',
      'true'
    );
  });

  it('carries what it is loading as text, for a reader who cannot see bars', () => {
    render(
      <DashboardSectionSkeleton
        label="Loading today's agenda..."
        testId='agenda-loading'
      />
    );

    expect(screen.getByText("Loading today's agenda...")).toBeInTheDocument();
  });

  /**
   * A live region would announce this on arrival, on a page every sign-in
   * lands on, four times over. The sentence is there to be found, not read out.
   */
  it('is not a live region', () => {
    render(
      <DashboardSectionSkeleton label='Loading' testId='agenda-loading' />
    );

    const skeleton = screen.getByTestId('agenda-loading');
    expect(skeleton).not.toHaveAttribute('aria-live');
    expect(skeleton).not.toHaveAttribute('role', 'status');
  });

  it('hides the bars themselves from assistive technology', () => {
    render(
      <DashboardSectionSkeleton label='Loading' testId='agenda-loading' />
    );

    const rows = screen
      .getByTestId('agenda-loading')
      .querySelectorAll('[data-testid="dashboard-section-skeleton-row"]');

    expect(rows.length).toBeGreaterThan(0);
    rows.forEach(row => expect(row).toHaveAttribute('aria-hidden', 'true'));
  });
});

describe('DashboardSectionPlaceholder', () => {
  describe('while the query is in flight', () => {
    it('draws the skeleton under the section id the card already published', () => {
      renderPlaceholder(true);

      expect(screen.getByTestId('agenda-loading')).toBeInTheDocument();
    });

    it('keeps the loading sentence the quiet line used to carry', () => {
      renderPlaceholder(true);

      expect(screen.getByTestId('agenda-loading')).toHaveTextContent(
        "Loading today's agenda..."
      );
    });

    it('says nothing about the section being unavailable', () => {
      renderPlaceholder(true);

      expect(
        screen.queryByTestId('agenda-unavailable')
      ).not.toBeInTheDocument();
    });
  });

  describe('when the section came back with nothing', () => {
    it('says so in one line beneath one icon, in the W29 idiom', () => {
      renderPlaceholder(false);

      const unavailable = screen.getByTestId('agenda-unavailable');
      expect(unavailable).toHaveTextContent("Today's agenda is unavailable.");
      expect(unavailable.querySelector('svg')).toHaveAttribute(
        'aria-hidden',
        'true'
      );
    });

    it('draws no skeleton beside it', () => {
      renderPlaceholder(false);

      expect(screen.queryByTestId('agenda-loading')).not.toBeInTheDocument();
    });

    /**
     * **W9** is explicit — "no error styling and no retry banner" — and the
     * page's own rule allows exactly two mutations, neither of them a retry.
     */
    it('offers no retry and raises no alert', () => {
      renderPlaceholder(false);

      expect(screen.queryByRole('button')).not.toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});
