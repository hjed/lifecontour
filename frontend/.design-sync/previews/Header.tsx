import { Breadcrumb, Header } from 'lifecontour-frontend';

/**
 * The app bar as it renders for a signed-in user: home affordance, centred
 * global search, theme toggle and the avatar menu. The preview harness signs
 * in as Alex Taylor, which is what drives the search box and avatar to appear.
 */
export function Default() {
  return <Header />;
}

/**
 * How the header actually sits in `app/layout.tsx` — sticky bar over the page
 * container, with the breadcrumb as the first thing inside it.
 */
export function InPageLayout() {
  return (
    <div className='bg-background'>
      <Header />
      <main className='container mx-auto px-4 py-6'>
        <Breadcrumb className='mb-4' />
        <h1 className='text-lg font-semibold'>Journals</h1>
        <p className='text-muted-foreground text-sm'>
          24 entries logged since 1 May 2024.
        </p>
      </main>
    </div>
  );
}
