import { useEffect, useRef } from 'react';
import { UserMenu } from 'lifecontour-frontend';

/**
 * The menu's open state is component-private (`DropdownMenu` is uncontrolled
 * inside `UserMenu`, which takes no props), so the open card is produced by
 * driving the real trigger rather than by hand-rolling the panel.
 *
 * Two details this needs: Radix opens on `pointerdown`, not `click`; and
 * `UserMenu` renders `null` until the session query resolves, so the trigger
 * does not exist on the first effect — hence the poll.
 */
function useAutoOpen(selector: string) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let tries = 0;
    const timer = setInterval(() => {
      const el = ref.current?.querySelector<HTMLElement>(selector);
      if (el) {
        clearInterval(timer);
        el.dispatchEvent(
          new PointerEvent('pointerdown', {
            bubbles: true,
            cancelable: true,
            button: 0,
          })
        );
      } else if (++tries > 100) {
        clearInterval(timer);
      }
    }, 50);
    return () => clearInterval(timer);
  }, [selector]);
  return ref;
}

/** Resting state: the signed-in user's initials, as the header renders them. */
export function Default() {
  return (
    <div className='flex items-center gap-2'>
      <UserMenu />
    </div>
  );
}

/** Opened — account label, profile and settings links, and sign out. */
export function OpenMenu() {
  const ref = useAutoOpen('[data-testid="user-menu"]');
  return (
    <div ref={ref} className='flex items-center gap-2'>
      <UserMenu />
    </div>
  );
}
