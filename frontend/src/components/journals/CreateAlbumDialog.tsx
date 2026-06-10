/**
 * CreateAlbumDialog (ITER11-006 Phase 2).
 *
 * Photo-selection dialog for creating an Immich album from a journal's date
 * range. Renders a grid of candidate photo thumbnails with checkboxes — all
 * selected by default — so the common case is "create an album with every
 * photo" and the user only needs to deselect the ones they don't want. Also
 * offers an optional public shared link, then calls the create-album API.
 */

'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  useCreateImmichAlbum,
  type ImmichPhoto,
} from '@/lib/api/immich-albums';

interface CreateAlbumDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly journalId: string;
  readonly photos: readonly ImmichPhoto[];
}

export function CreateAlbumDialog({
  open,
  onOpenChange,
  journalId,
  photos,
}: CreateAlbumDialogProps) {
  // All photos selected by default — the user deselects what they don't want.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(photos.map(photo => photo.id))
  );
  const [createSharedLink, setCreateSharedLink] = useState(false);

  const createAlbum = useCreateImmichAlbum();

  const togglePhoto = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleConfirm = () => {
    createAlbum.mutate(
      {
        journalId,
        assetIds: Array.from(selectedIds),
        createSharedLink,
      },
      {
        onSuccess: () => {
          onOpenChange(false);
        },
      }
    );
  };

  const selectedCount = selectedIds.size;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className='sm:max-w-[640px]'
        data-testid='create-album-dialog'
      >
        <DialogHeader>
          <DialogTitle>Create Photo Album</DialogTitle>
          <DialogDescription>
            Select the photos to include in the album. All photos are selected
            by default — deselect any you don&apos;t want.
          </DialogDescription>
        </DialogHeader>

        <div className='space-y-4 py-2'>
          <ScrollArea className='h-72 rounded-md border p-3'>
            <div
              className='grid grid-cols-2 gap-3 sm:grid-cols-3'
              role='group'
              aria-label='Photos to include in the album'
            >
              {photos.map(photo => {
                const selected = selectedIds.has(photo.id);
                // The whole tile is a single checkbox control so clicking the
                // thumbnail toggles selection. The Radix Checkbox is a
                // visual-only indicator (aria-hidden + non-interactive) to
                // avoid a nested, separately-clickable control.
                return (
                  <button
                    key={photo.id}
                    type='button'
                    role='checkbox'
                    aria-checked={selected}
                    aria-label={`Include ${photo.originalFileName}`}
                    onClick={() => togglePhoto(photo.id)}
                    data-testid={`photo-checkbox-${photo.id}`}
                    className='group focus-visible:ring-ring relative block w-full cursor-pointer overflow-hidden rounded-md border text-left focus-visible:ring-2 focus-visible:outline-none'
                  >
                    <img
                      src={photo.thumbnailUrl}
                      alt={photo.originalFileName}
                      className='h-28 w-full object-cover'
                    />
                    <span className='bg-background/80 absolute top-1 left-1 rounded p-0.5'>
                      <Checkbox
                        checked={selected}
                        aria-hidden
                        tabIndex={-1}
                        className='pointer-events-none'
                      />
                    </span>
                  </button>
                );
              })}
            </div>
          </ScrollArea>

          <p
            className='text-muted-foreground text-sm'
            data-testid='create-album-selected-count'
          >
            {selectedCount} of {photos.length} photos selected
          </p>

          <div className='flex items-center space-x-2'>
            <Checkbox
              id='create-shared-link'
              checked={createSharedLink}
              onCheckedChange={checked => setCreateSharedLink(checked === true)}
              data-testid='create-shared-link-checkbox'
            />
            <Label htmlFor='create-shared-link' className='font-medium'>
              Create public shared link
            </Label>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant='outline'
            onClick={() => onOpenChange(false)}
            disabled={createAlbum.isPending}
          >
            Cancel
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={selectedCount === 0 || createAlbum.isPending}
            aria-busy={createAlbum.isPending}
            data-testid='create-album-confirm'
          >
            {createAlbum.isPending ? (
              <>
                <Loader2 className='mr-2 h-4 w-4 animate-spin' />
                Creating album…
              </>
            ) : (
              'Create Album'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
