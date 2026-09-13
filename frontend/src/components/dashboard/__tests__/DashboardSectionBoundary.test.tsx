/**
 * @jest-environment jsdom
 *
 * The backstop behind *"sections render independently"* (ITER18-004 Phase 16).
 *
 * The three cards each guard the one or two fields they read, and each recorded
 * the same limit: the guard protects `tomorrow`, or `dates`, or `tasks`, and
 * nothing protects the card from an entry inside the list being malformed. A
 * component that throws out of render takes its **whole React tree** down with
 * it, so before this boundary one bad row blanked the page — the summary, the
 * other two sections and the header included. The specification's independence
 * claim has to survive a section that breaks its contract, not only one that
 * politely reports itself unavailable.
 *
 * These tests throw on purpose, and React writes every error a boundary catches
 * to `console.error`. That is desirable in the app and only noise here, so it is
 * silenced per test rather than globally: a suite that muted it for good would
 * also mute the warnings it wants to hear.
 */

import { render, screen } from '@testing-library/react';
import { SectionErrorBoundary } from '../DashboardSectionBoundary';

function Explodes(): React.ReactElement {
  throw new Error('a row broke its contract');
}

function Fine() {
  return <p>Two things on today</p>;
}

/** React logs every caught error; these tests cause them deliberately. */
function silenceReactErrorLogging() {
  return jest.spyOn(console, 'error').mockImplementation(() => {});
}

describe('SectionErrorBoundary', () => {
  let consoleError: jest.SpyInstance;

  beforeEach(() => {
    consoleError = silenceReactErrorLogging();
  });

  afterEach(() => {
    consoleError.mockRestore();
  });

  it('renders its children while nothing throws', () => {
    render(
      <SectionErrorBoundary fallback={<p>Unavailable</p>}>
        <Fine />
      </SectionErrorBoundary>
    );

    expect(screen.getByText('Two things on today')).toBeInTheDocument();
    expect(screen.queryByText('Unavailable')).not.toBeInTheDocument();
  });

  it('renders the fallback when a child throws out of render', () => {
    render(
      <SectionErrorBoundary fallback={<p>Unavailable</p>}>
        <Explodes />
      </SectionErrorBoundary>
    );

    expect(screen.getByText('Unavailable')).toBeInTheDocument();
  });

  /**
   * The whole point, stated as the specification states it: the section that
   * broke is the only one that goes.
   */
  it('leaves everything outside it on the page', () => {
    render(
      <div>
        <p>The summary</p>
        <SectionErrorBoundary fallback={<p>Unavailable</p>}>
          <Explodes />
        </SectionErrorBoundary>
        <p>The upcoming dates</p>
      </div>
    );

    expect(screen.getByText('The summary')).toBeInTheDocument();
    expect(screen.getByText('The upcoming dates')).toBeInTheDocument();
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
  });

  it('keeps a sibling boundary rendering its own children', () => {
    render(
      <div>
        <SectionErrorBoundary fallback={<p>Agenda unavailable</p>}>
          <Explodes />
        </SectionErrorBoundary>
        <SectionErrorBoundary fallback={<p>Tasks unavailable</p>}>
          <Fine />
        </SectionErrorBoundary>
      </div>
    );

    expect(screen.getByText('Agenda unavailable')).toBeInTheDocument();
    expect(screen.getByText('Two things on today')).toBeInTheDocument();
    expect(screen.queryByText('Tasks unavailable')).not.toBeInTheDocument();
  });

  /**
   * A boundary that latched for the life of the page would make one bad
   * payload permanent: the window-focus refetch and the anchor-day refresh
   * both bring a fresh read, and a section that recovered would keep showing
   * *unavailable* until the user reloaded. `resetKey` is what a fresh read
   * moves, and it is only consulted while the boundary is holding an error.
   */
  it('tries again when a fresh read arrives', () => {
    const { rerender } = render(
      <SectionErrorBoundary fallback={<p>Unavailable</p>} resetKey='1'>
        <Explodes />
      </SectionErrorBoundary>
    );
    expect(screen.getByText('Unavailable')).toBeInTheDocument();

    rerender(
      <SectionErrorBoundary fallback={<p>Unavailable</p>} resetKey='2'>
        <Fine />
      </SectionErrorBoundary>
    );

    expect(screen.getByText('Two things on today')).toBeInTheDocument();
    expect(screen.queryByText('Unavailable')).not.toBeInTheDocument();
  });

  it('holds the fallback while the read has not moved', () => {
    const { rerender } = render(
      <SectionErrorBoundary fallback={<p>Unavailable</p>} resetKey='1'>
        <Explodes />
      </SectionErrorBoundary>
    );

    rerender(
      <SectionErrorBoundary fallback={<p>Unavailable</p>} resetKey='1'>
        <Fine />
      </SectionErrorBoundary>
    );

    expect(screen.getByText('Unavailable')).toBeInTheDocument();
  });

  it('goes back to the fallback when the fresh read is broken too', () => {
    const { rerender } = render(
      <SectionErrorBoundary fallback={<p>Unavailable</p>} resetKey='1'>
        <Explodes />
      </SectionErrorBoundary>
    );

    rerender(
      <SectionErrorBoundary fallback={<p>Unavailable</p>} resetKey='2'>
        <Explodes />
      </SectionErrorBoundary>
    );

    expect(screen.getByText('Unavailable')).toBeInTheDocument();
  });
});
