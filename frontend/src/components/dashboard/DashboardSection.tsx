/**
 * DashboardSection — the labelled wrapper each evidence section sits in.
 *
 * **W4**: a `section` named by a visually hidden `h2`, with the *visible* title
 * left to the card header inside it. Hiding the heading rather than dropping it
 * is what gives the page a real landmark structure — a screen-reader user can
 * jump between Agenda, Tasks and Upcoming dates — without drawing the title
 * twice for everyone else.
 */

interface DashboardSectionProps {
  /**
   * Stable id for the section; the heading takes `${id}-heading` and the
   * section points at it, so the name has one source.
   */
  readonly id: string;
  readonly title: string;
  readonly children: React.ReactNode;
}

export function DashboardSection({
  id,
  title,
  children,
}: DashboardSectionProps) {
  const headingId = `${id}-heading`;

  return (
    <section
      aria-labelledby={headingId}
      data-testid={`dashboard-section-${id}`}
    >
      <h2 id={headingId} className='sr-only'>
        {title}
      </h2>
      {children}
    </section>
  );
}
