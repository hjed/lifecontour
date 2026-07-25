/**
 * JournalTagContextMenu — wraps a sidebar journal tag row with its management
 * menu, mirroring the contacts `TagContextMenu`.
 *
 * The wrapped row contains the focusable tag link, so the browser's keyboard
 * context-menu key reaches the trigger too — the menu is not mouse-only.
 */

'use client';

import React, { useState } from 'react';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import { Pencil } from 'lucide-react';
import { JournalTagManagementDialog } from './JournalTagManagementDialog';
import type { JournalTag } from '@/types/journals';

export interface JournalTagContextMenuProps {
  readonly children: React.ReactNode;
  readonly tag: JournalTag;
}

export function JournalTagContextMenu({
  children,
  tag,
}: JournalTagContextMenuProps) {
  const [showEditDialog, setShowEditDialog] = useState(false);

  return (
    <>
      <ContextMenu>
        <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
        <ContextMenuContent className='w-48'>
          <ContextMenuItem onSelect={() => setShowEditDialog(true)}>
            <Pencil className='mr-2 h-4 w-4' aria-hidden='true' />
            Edit Tag
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>

      {/* Kept mounted so the dialog's open prop drives visibility, matching the
          contacts menu. */}
      <JournalTagManagementDialog
        open={showEditDialog}
        onOpenChange={setShowEditDialog}
        tag={tag}
      />
    </>
  );
}
