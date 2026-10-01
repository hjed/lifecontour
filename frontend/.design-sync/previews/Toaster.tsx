import * as React from 'react';
import * as DS from 'lifecontour-frontend';
import { Toaster } from 'lifecontour-frontend';
import { toast as sonnerToast } from 'sonner';

/**
 * `<Toaster />` is an empty portal host until something calls `toast()`, so
 * each cell fires its toasts on mount.
 *
 * IMPORTANT: the DS bundle inlines its own copy of `sonner`, and preview files
 * bundle a *second* copy from node_modules. A `toast()` from the preview's copy
 * therefore never reaches the bundled `<Toaster />`. Re-exporting `toast` from
 * `.design-sync/ds-entry.ts` (`export { toast } from 'sonner';`) puts both on
 * the same instance — this preview picks that up automatically as soon as it
 * exists, and falls back to the preview-local copy until then.
 */
const toast =
  (DS as unknown as { toast?: typeof sonnerToast }).toast ?? sonnerToast;

function useToastsOnMount(fire: () => void) {
  React.useEffect(() => {
    fire();
    return () => toast.dismiss();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

export function Success() {
  useToastsOnMount(() => {
    toast.success('Journal entry saved', {
      description: 'Morning run · 14 July 2026',
      duration: Infinity,
    });
  });
  return (
    <div className='relative w-full' style={{ minHeight: '160px' }}>
      <Toaster position='top-center' expand />
    </div>
  );
}

export function Variants() {
  useToastsOnMount(() => {
    toast.success('Strava sync finished', {
      description: '14 activities imported',
      duration: Infinity,
    });
    toast.error('Could not reach Immich', {
      description: 'Photo sync failed at 6:12 am',
      duration: Infinity,
    });
    toast.info('3 merge candidates found', {
      description: 'Review before the next Google Contacts sync',
      duration: Infinity,
    });
  });
  return (
    <div className='relative w-full' style={{ minHeight: '300px' }}>
      <Toaster position='top-center' expand visibleToasts={5} />
    </div>
  );
}

export function WithAction() {
  useToastsOnMount(() => {
    toast('Contact deleted', {
      description: 'Tom Whitfield was removed from your contacts',
      action: { label: 'Undo', onClick: () => undefined },
      duration: Infinity,
    });
  });
  return (
    <div className='relative w-full' style={{ minHeight: '160px' }}>
      <Toaster position='top-center' expand />
    </div>
  );
}
