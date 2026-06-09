/**
 * CreateAlbumButton (ITER11-006 Phase 2).
 *
 * Shows a "Create Album" action on the journal edit screen when an Immich album
 * can be created for the journal, i.e. when:
 *   - the Immich integration is connected,
 *   - the journal has an event date range, and
 *   - the journal does not already have a linked album (no PHOTO_ALBUM type).
 *
 * Clicking it searches Immich for photos in the journal's date range (with a
 * loading state) and opens the photo-selection dialog with the results.
 */

'use client';

import { useState } from 'react';
import { ImagePlus, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { useIntegrations } from '@/lib/api/integrations';
import {
  useImmichPhotoSearch,
  type ImmichPhoto,
} from '@/lib/api/immich-albums';
import { JournalType, type Journal } from '@/types/journals';
import { CreateAlbumDialog } from './CreateAlbumDialog';

interface CreateAlbumButtonProps {
  readonly journal: Journal;
}

export function CreateAlbumButton({ journal }: CreateAlbumButtonProps) {
  const { data: integrationsResponse } = useIntegrations();
  const photoSearch = useImmichPhotoSearch();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [photos, setPhotos] = useState<ImmichPhoto[]>([]);

  const immichConnected =
    integrationsResponse?.data?.find(i => i.id === 'immich')?.attributes
      ?.status === 'connected';
  // Require a complete range: the backend photo search expands both ends, so a
  // half-open range would surface the button only to fail the search later.
  const hasDateRange =
    Boolean(journal.event_date_range?.start) &&
    Boolean(journal.event_date_range?.end);
  const alreadyLinked = (journal.types ?? []).includes(JournalType.PHOTO_ALBUM);

  // Visibility: only when an album can actually be created.
  if (!immichConnected || !hasDateRange || alreadyLinked) {
    return null;
  }

  const handleClick = () => {
    photoSearch.mutate(journal.id, {
      onSuccess: results => {
        // Spec trigger condition: only present the creation flow when Immich
        // actually has photos for the journal's date range.
        if (results.length === 0) {
          toast.info('No Immich photos found for this journal’s dates.');
          return;
        }
        setPhotos(results);
        setDialogOpen(true);
      },
    });
  };

  return (
    <>
      <Button
        variant='outline'
        size='sm'
        onClick={handleClick}
        disabled={photoSearch.isPending}
        aria-busy={photoSearch.isPending}
        className='gap-2'
        data-testid='create-album-button'
      >
        {photoSearch.isPending ? (
          <Loader2 className='h-4 w-4 animate-spin' />
        ) : (
          <ImagePlus className='h-4 w-4' />
        )}
        Create Album
      </Button>

      {dialogOpen && (
        <CreateAlbumDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          journalId={journal.id}
          photos={photos}
        />
      )}
    </>
  );
}
