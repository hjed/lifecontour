'use client';

import React, { useState } from 'react';
import { TagResource } from '@/types/contacts';
import { TagManagementDialog } from './TagManagementDialog';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import { Pencil } from 'lucide-react';

export interface TagContextMenuProps {
  readonly children: React.ReactNode;
  readonly tag: TagResource;
}

export function TagContextMenu({ children, tag }: TagContextMenuProps) {
  const [showEditDialog, setShowEditDialog] = useState(false);

  return (
    <>
      <ContextMenu>
        <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
        <ContextMenuContent className='w-48'>
          <ContextMenuItem onSelect={() => setShowEditDialog(true)}>
            <Pencil className='mr-2 h-4 w-4' />
            Edit Tag
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>

      {/* We unmount/mount cautiously or just rely on open prop.
          Given it's a dialog with internal State for Form, we just keep it mounted
          and let the open prop control visibility. */}
      <TagManagementDialog
        open={showEditDialog}
        onOpenChange={setShowEditDialog}
        tag={tag}
      />
    </>
  );
}
