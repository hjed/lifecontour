import { useEffect, useRef } from 'react';
import { NewDialog } from 'lifecontour-frontend';

/**
 * The top bar's New dialog, opened on its first type, Journal. Its open state
 * is private to `NewDialog`, so the card clicks the real trigger on mount.
 *
 * The card's viewport is desktop width, where New is a centred dialog. Below
 * the `md` breakpoint the same dialog becomes a sheet pinned to the top of the
 * screen, full width with rounded bottom corners and 44px controls. Both looks
 * come from one component, switched by a media query, so a single card can
 * only show one of them.
 *
 * The switch across the top lists the types the dialog can create, in the
 * specification's order: Journal, then Contact, with Task to come first. Each
 * type's panel is the app's own create form (`JournalCreateForm`,
 * `ContactForm`), so the card shows the journal form as `/journals/new` does;
 * Contact is one press away on the switch.
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
