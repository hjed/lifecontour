import { DesktopSidebar, Header } from 'lifecontour-frontend';

/**
 * The desktop sidebar is `md:fixed` — in the app it pins itself below the
 * header for the full height of the viewport. A transformed wrapper makes it
 * the containing block for that fixed positioning, so the card shows the real
 * component at its real size instead of it escaping over the whole page.
 */
const frame = {
  position: 'relative' as const,
  transform: 'translateZ(0)',
  height: '600px',
  overflow: 'hidden',
};

/**
 * Sections come from `SidebarContext`: Contacts starts expanded, Journals and
 * Integrations collapsed. The tag tree is fed by `useTags()`, which has no API
 * to reach in a static preview, so the Contacts section shows its static items
 * and the Create Tag action only.
 */
export function Default() {
  return (
    <div style={frame}>
      <DesktopSidebar />
    </div>
  );
}

/** Its real placement: under the sticky header, with `md:pl-64` page content. */
export function InAppLayout() {
  return (
    <div style={frame} className='bg-background'>
      <Header />
      <DesktopSidebar />
      <main className='md:pl-64'>
        <div className='px-6 py-6'>
          <h1 className='text-lg font-semibold'>Contacts</h1>
          <p className='text-muted-foreground text-sm'>
            118 contacts · 12 favourites
          </p>
        </div>
      </main>
    </div>
  );
}
