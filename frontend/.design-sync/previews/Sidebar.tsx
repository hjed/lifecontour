import { Sidebar } from 'personal-management-frontend';

/**
 * `Sidebar` renders both variants and lets the breakpoint pick one: the
 * `DesktopSidebar` rail from `md` up, the `MobileSidebar` trigger below it.
 * Cards capture at 900px wide, so this is the desktop half; the mobile trigger
 * is present in the DOM but `md:hidden`.
 *
 * The rail is `md:fixed`, so the transformed wrapper gives it a containing
 * block and keeps it inside the card.
 */
export function Default() {
  return (
    <div
      style={{
        position: 'relative',
        transform: 'translateZ(0)',
        height: '600px',
        overflow: 'hidden',
      }}
    >
      <Sidebar />
    </div>
  );
}
