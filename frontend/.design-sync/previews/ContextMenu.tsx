import { useEffect, useRef } from 'react';
import {
  Badge,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuCheckboxItem,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuTrigger,
} from 'lifecontour-frontend';
import { Copy, Pencil, Star, Tag, Trash2, UserPlus } from 'lucide-react';

/**
 * Radix's ContextMenu anchors its content to the right-click POINT, so simply
 * passing `open` would pin the menu to the viewport's top-left corner. The
 * preview instead replays a real `contextmenu` event at a chosen offset inside
 * the trigger, which is what a user's right-click does — the menu then lands
 * where it would in the product.
 */
function useRightClick<T extends HTMLElement>(dx: number, dy: number) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.dispatchEvent(
      new MouseEvent('contextmenu', {
        bubbles: true,
        cancelable: true,
        clientX: rect.left + dx,
        clientY: rect.top + dy,
      })
    );
  }, [dx, dy]);
  return ref;
}

/** Right-clicking a journal entry in the list. */
export function EntryActions() {
  const ref = useRightClick<HTMLDivElement>(244, 92);
  return (
    <ContextMenu modal={false}>
      <ContextMenuTrigger asChild>
        <div ref={ref} className='w-72 rounded-md border p-3'>
          <p className='text-sm font-medium'>Morning run along the Yarra</p>
          <p className='text-muted-foreground mt-1 text-xs'>
            14 July 2026 · 8.2 km
          </p>
          <div className='mt-2 flex gap-1'>
            <Badge variant='secondary'>Running</Badge>
            <Badge variant='secondary'>Melbourne</Badge>
          </div>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent className='w-56'>
        <ContextMenuLabel>Journal entry</ContextMenuLabel>
        <ContextMenuSeparator />
        <ContextMenuItem>
          <Pencil className='mr-2 h-4 w-4' />
          Edit entry
          <ContextMenuShortcut>⌘E</ContextMenuShortcut>
        </ContextMenuItem>
        <ContextMenuItem>
          <Tag className='mr-2 h-4 w-4' />
          Add tag
        </ContextMenuItem>
        <ContextMenuItem>
          <UserPlus className='mr-2 h-4 w-4' />
          Link to contact
        </ContextMenuItem>
        <ContextMenuItem>
          <Copy className='mr-2 h-4 w-4' />
          Duplicate
          <ContextMenuShortcut>⌘D</ContextMenuShortcut>
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuCheckboxItem checked>
          Pin to dashboard
        </ContextMenuCheckboxItem>
        <ContextMenuSeparator />
        <ContextMenuItem className='text-destructive'>
          <Trash2 className='mr-2 h-4 w-4' />
          Delete journal
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/** Right-clicking a tag chip — ported from the contacts TagContextMenu. */
export function TagActions() {
  const ref = useRightClick<HTMLSpanElement>(148, 36);
  return (
    <div className='flex items-center gap-2'>
      <ContextMenu modal={false}>
        <ContextMenuTrigger asChild>
          <span
            ref={ref}
            className='inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm'
          >
            <Tag className='text-muted-foreground h-4 w-4' />
            Bushwalking
            <span className='text-muted-foreground text-xs'>41</span>
          </span>
        </ContextMenuTrigger>
        <ContextMenuContent className='w-48'>
          <ContextMenuItem>
            <Pencil className='mr-2 h-4 w-4' />
            Edit tag
          </ContextMenuItem>
          <ContextMenuItem>
            <Star className='mr-2 h-4 w-4' />
            Mark as favourite
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem className='text-destructive'>
            <Trash2 className='mr-2 h-4 w-4' />
            Delete tag
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
    </div>
  );
}
