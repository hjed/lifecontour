/**
 * DashboardSectionBoundary — the backstop behind *"sections render
 * independently"*.
 *
 * Each card guards the field it reads — the agenda's `tomorrow`, the dates'
 * `dates`, the tasks' `tasks` — and each recorded the same limit when it did:
 * the guard protects the one field somebody thought of, and nothing protects
 * the card from a malformed *entry* inside the list. A component that throws
 * out of render takes its whole React tree with it, so one bad row used to
 * blank the page: the summary, the other two sections and the header included.
 * The specification's independence claim has to survive a section that breaks
 * its contract, not only one that reports itself unavailable, and that is what
 * this adds.
 *
 * **The guards stay in front of it.** They are cheap, precise, and render the
 * section's unavailable state without an exception — React reports every error
 * a boundary catches to the console, and a payload shape we already know how to
 * handle should not be reported as a defect. The boundary is for what the
 * guards could not foresee.
 *
 * **It does not latch.** A boundary that held for the life of the page would
 * make one bad payload permanent, and both the window-focus refetch and the
 * anchor-day refresh exist to bring a better one. `resetKey` is what a fresh
 * read moves — the cards pass the query's own update stamps — and it is
 * consulted **only** while an error is being held, so the ordinary path never
 * remounts and a card's expansion state survives every refetch.
 */

'use client';

import { Component } from 'react';
import { useHomeDashboard } from '@/lib/api/home-dashboard';

interface DashboardSectionBoundaryProps {
  readonly children: React.ReactNode;
  /**
   * Drawn instead of the children once one of them has thrown. A section
   * passes its own card shell showing its unavailable state, so a broken
   * section still reads as a section rather than as a missing one.
   */
  readonly fallback: React.ReactNode;
  /**
   * Changes when there is new data worth trying again on. Optional so the
   * boundary is usable — and testable — without a query behind it.
   */
  readonly resetKey?: string;
}

interface DashboardSectionBoundaryState {
  readonly hasError: boolean;
}

class SectionErrorBoundary extends Component<
  DashboardSectionBoundaryProps,
  DashboardSectionBoundaryState
> {
  // A class because `getDerivedStateFromError` has no hook equivalent: React
  // still provides no function-component way to catch a render error. A
  // dependency (`react-error-boundary`) would buy resets and retry callbacks
  // this page has no use for — W9 is explicit that there is no retry control.
  override state: DashboardSectionBoundaryState = { hasError: false };

  static getDerivedStateFromError(): DashboardSectionBoundaryState {
    return { hasError: true };
  }

  override componentDidUpdate(prevProps: DashboardSectionBoundaryProps): void {
    // Guarded on `hasError` so the ordinary path never calls `setState` here.
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false });
    }
  }

  override render(): React.ReactNode {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

type DashboardSectionBoundaryOwnProps = Omit<
  DashboardSectionBoundaryProps,
  'resetKey'
>;

export function DashboardSectionBoundary({
  children,
  fallback,
}: DashboardSectionBoundaryOwnProps) {
  // Both stamps, because either kind of answer is a reason to try again: a
  // successful refetch may carry a payload the section can render, and a failed
  // one moves the card to its own unavailable state anyway.
  const { dataUpdatedAt, errorUpdatedAt } = useHomeDashboard();

  return (
    <SectionErrorBoundary
      fallback={fallback}
      resetKey={`${dataUpdatedAt}:${errorUpdatedAt}`}
    >
      {children}
    </SectionErrorBoundary>
  );
}

/** The class itself, for tests that drive `resetKey` without a query. */
export { SectionErrorBoundary };
