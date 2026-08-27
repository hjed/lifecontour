/**
 * @jest-environment jsdom
 *
 * The W4 section wrapper: a labelled `section` whose heading is visually
 * hidden, with the visible title left to the card inside it. Every evidence
 * section on the dashboard is built from it, so these are the accessibility
 * guarantees the whole grid inherits.
 */

import { render, screen } from '@testing-library/react';
import { DashboardSection } from '../DashboardSection';

describe('DashboardSection', () => {
  function renderSection() {
    return render(
      <DashboardSection id='agenda' title='Agenda'>
        <p>The card</p>
      </DashboardSection>
    );
  }

  it('is a region named by its heading', () => {
    renderSection();

    expect(screen.getByRole('region', { name: 'Agenda' })).toBeInTheDocument();
  });

  it('hides its heading visually while leaving it to assistive tech', () => {
    renderSection();

    const heading = screen.getByRole('heading', { level: 2, name: 'Agenda' });
    expect(heading).toHaveClass('sr-only');
  });

  it('points the section at its own heading rather than repeating the name', () => {
    renderSection();

    const section = screen.getByRole('region', { name: 'Agenda' });
    const heading = screen.getByRole('heading', { level: 2, name: 'Agenda' });
    expect(section).toHaveAttribute('aria-labelledby', heading.id);
  });

  it('renders the card it wraps', () => {
    renderSection();

    expect(screen.getByText('The card')).toBeInTheDocument();
  });
});
