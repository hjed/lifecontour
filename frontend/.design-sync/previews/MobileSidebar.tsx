import { useEffect, useRef } from 'react';
import { MobileSidebar } from 'personal-management-frontend';

/**
 * The drawer's open state is component-private (`Sheet` is driven by a
 * `useState` inside `MobileSidebar`, which only takes `className`), so the card
 * opens it by clicking the real trigger on mount — nothing here reimplements
 * the panel.
 */
export function Default() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current
      ?.querySelector<HTMLElement>('[data-testid="mobile-nav-trigger"]')
      ?.click();
  }, []);

  return (
    <div ref={ref} className='p-4'>
      <MobileSidebar />
    </div>
  );
}
