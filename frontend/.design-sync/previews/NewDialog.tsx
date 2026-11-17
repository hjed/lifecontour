import { useEffect, useRef } from 'react';
import { NewDialog } from 'lifecontour-frontend';

/**
 * The top bar's New dialog, opened on the Contact type. Its open state is
 * private to `NewDialog`, so the card clicks the real trigger on mount.
 *
 * The card's viewport is desktop width, where New is a centred dialog. Below
 * the `md` breakpoint the same dialog becomes a sheet pinned to the top of the
 * screen, full width with rounded bottom corners and 44px controls. Both looks
 * come from one component, switched by a media query, so a single card can
 * only show one of them.
 *
 * The switch across the top lists the types the dialog can create; Contact is
 * the only one so far, and Journal and Task join it as further entries.
 */
export function Open() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current
      ?.querySelector<HTMLElement>('[data-testid="new-button"]')
      ?.click();
  }, []);

  return (
    <div ref={ref} className='p-4'>
      <NewDialog />
    </div>
  );
}
