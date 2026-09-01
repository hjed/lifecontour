/**
 * @jest-environment jsdom
 *
 * The summary card's key-stats footer (**W10**).
 *
 * Four label/value pairs — Journals, Events, Contacts, Avg Mood — drawn from
 * counters the summary entity already carries. The footer is a pure function of
 * those four numbers, so it is tested without a query: *whether* it is drawn at
 * all is the card's decision (**W10** says the generated state only), and that
 * is asserted in `DashboardSummaryCard.test.tsx`.
 */

import { render, screen } from '@testing-library/react';
import { SummaryKeyStats } from '../SummaryKeyStats';

/** Read the value rendered under a label, via the `dt`/`dd` pairing. */
function valueFor(label: string): string {
  const term = screen.getByText(label);
  const value = term.nextElementSibling;
  expect(value?.tagName).toBe('DD');
  return value?.textContent ?? '';
}

describe('SummaryKeyStats (W10)', () => {
  it('draws all four label/value pairs', () => {
    render(
      <SummaryKeyStats
        journalCount={3}
        eventCount={2}
        contactCount={4}
        moodAverage={7.5}
      />
    );

    expect(valueFor('Journals')).toBe('3');
    expect(valueFor('Events')).toBe('2');
    expect(valueFor('Contacts')).toBe('4');
    expect(valueFor('Avg Mood')).toBe('7.5/10');
  });

  /**
   * The journals view hides a zero count; the dashboard does not. A footer
   * whose columns come and go with the data changes shape between days, and
   * "no events today" is a fact worth reading rather than an absence to infer.
   */
  it('keeps a pair whose count is zero rather than dropping the column', () => {
    render(
      <SummaryKeyStats
        journalCount={1}
        eventCount={0}
        contactCount={0}
        moodAverage={6}
      />
    );

    expect(valueFor('Events')).toBe('0');
    expect(valueFor('Contacts')).toBe('0');
  });

  it('shows mood out of ten to one decimal place', () => {
    render(
      <SummaryKeyStats
        journalCount={1}
        eventCount={1}
        contactCount={1}
        moodAverage={8}
      />
    );

    expect(valueFor('Avg Mood')).toBe('8.0/10');
  });

  /**
   * Most days rate nothing. A dash says "nothing rated" without claiming a
   * mood of zero, and keeps the row four columns wide either way.
   */
  it('shows a dash for an unrated day, keeping the other three pairs', () => {
    render(
      <SummaryKeyStats
        journalCount={2}
        eventCount={1}
        contactCount={0}
        moodAverage={null}
      />
    );

    expect(valueFor('Avg Mood')).toBe('—');
    expect(valueFor('Journals')).toBe('2');
    expect(valueFor('Events')).toBe('1');
    expect(valueFor('Contacts')).toBe('0');
  });

  it('pairs every label with its value as a description list', () => {
    const { container } = render(
      <SummaryKeyStats
        journalCount={3}
        eventCount={2}
        contactCount={4}
        moodAverage={7.5}
      />
    );

    // `dt`/`dd` is what lets a screen reader read "Avg Mood, 7.5 out of 10"
    // as one pair rather than as two unrelated strings.
    expect(container.querySelectorAll('dl')).toHaveLength(1);
    expect(container.querySelectorAll('dt')).toHaveLength(4);
    expect(container.querySelectorAll('dd')).toHaveLength(4);
  });

  it('labels the pairs in muted uppercase over their values', () => {
    render(
      <SummaryKeyStats
        journalCount={3}
        eventCount={2}
        contactCount={4}
        moodAverage={7.5}
      />
    );

    expect(screen.getByText('Journals')).toHaveClass(
      'text-muted-foreground',
      'uppercase'
    );
  });
});
