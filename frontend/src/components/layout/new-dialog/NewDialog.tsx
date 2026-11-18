'use client';

/**
 * The top bar's New control and the dialog it opens.
 *
 * One dialog serves every viewport: below `md` it is a sheet pinned to the top
 * of the screen, from `md` up a centred dialog. The type switch lists the
 * entries of a registry, and every type's panel stays mounted while the dialog
 * is open, so what was typed in one type survives switching to another.
 * Closing the dialog discards it.
 */

import { useRef, useState } from 'react';
import { Plus, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { UI_TEXT } from '@/lib/constants';
import { cn } from '@/lib/utils';

import { NEW_ENTITY_TYPES } from './registry';
import type { NewEntityId, NewEntityType } from './types';

export interface NewDialogProps {
  /** The types offered, in switch order. Defaults to the app registry. */
  readonly types?: readonly NewEntityType[];
}

const panelId = (id: NewEntityId) => `new-dialog-panel-${id}`;

export function NewDialog({ types = NEW_ENTITY_TYPES }: NewDialogProps) {
  const [open, setOpen] = useState(false);
  // A new key per opening resets the selected type; Radix unmounts the
  // panels on close, which discards what was typed.
  const [opening, setOpening] = useState(0);
  // Mirrors `opening` for callbacks that outlive their opening, such as a
  // create that resolves after the dialog was dismissed and reopened.
  const currentOpening = useRef(0);

  const handleOpenChange = (next: boolean) => {
    if (next) {
      currentOpening.current += 1;
      setOpening(currentOpening.current);
    }
    setOpen(next);
  };

  /** Closes the dialog only if that opening is still the one on screen. */
  const closeOpening = (closing: number) => {
    if (closing === currentOpening.current) setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          size='sm'
          className='size-11 px-0 md:h-8 md:w-auto md:px-3'
          data-testid='new-button'
        >
          <Plus aria-hidden='true' />
          <span className='sr-only md:not-sr-only'>{UI_TEXT.NEW}</span>
        </Button>
      </DialogTrigger>
      <NewDialogContent
        key={opening}
        types={types}
        onClose={() => closeOpening(opening)}
      />
    </Dialog>
  );
}

interface NewDialogContentProps {
  readonly types: readonly NewEntityType[];
  readonly onClose: () => void;
}

function NewDialogContent({ types, onClose }: NewDialogContentProps) {
  const [selected, setSelected] = useState<NewEntityId | undefined>(
    types[0]?.id
  );

  return (
    <DialogContent
      showCloseButton={false}
      data-testid='new-dialog'
      className={cn(
        // Phones: a sheet across the top of the screen.
        'top-0 left-0 max-h-[100dvh] w-full max-w-none translate-x-0 translate-y-0 gap-4 overflow-y-auto rounded-none rounded-b-xl border-x-0 border-t-0 p-4 sm:max-w-none',
        // Desktop: the centred dialog.
        'md:top-[50%] md:left-[50%] md:max-h-[90dvh] md:max-w-lg md:translate-x-[-50%] md:translate-y-[-50%] md:rounded-lg md:border md:p-6'
      )}
    >
      <div className='flex items-center justify-between gap-2'>
        <DialogTitle>{UI_TEXT.NEW}</DialogTitle>
        <DialogClose asChild>
          <Button
            variant='ghost'
            size='icon'
            className='text-muted-foreground size-11 md:size-8'
          >
            <XIcon aria-hidden='true' />
            <span className='sr-only'>{UI_TEXT.CLOSE}</span>
          </Button>
        </DialogClose>
      </div>
      <DialogDescription className='sr-only'>
        {UI_TEXT.NEW_DESCRIPTION}
      </DialogDescription>

      <div
        role='group'
        aria-label={UI_TEXT.NEW_TYPE_SWITCH}
        className='bg-muted grid auto-cols-fr grid-flow-col gap-1 rounded-lg p-1'
      >
        {types.map(({ id, label, icon: Icon }) => {
          const pressed = id === selected;
          return (
            <button
              key={id}
              type='button'
              aria-pressed={pressed}
              aria-controls={panelId(id)}
              onClick={() => setSelected(id)}
              className={cn(
                'focus-visible:ring-ring inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none md:min-h-9',
                pressed
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              <Icon aria-hidden='true' className='size-4' />
              {label}
            </button>
          );
        })}
      </div>

      {types.map(({ id, label, Panel }) => (
        <section
          key={id}
          id={panelId(id)}
          aria-label={label}
          hidden={id !== selected}
          // A grid item defaults to its content's min width, so a wide form
          // (the journal's) would stretch the column past the sheet's edge.
          className='min-w-0'
        >
          <Panel onCreated={onClose} onCancel={onClose} />
        </section>
      ))}
    </DialogContent>
  );
}
