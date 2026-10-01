import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from 'lifecontour-frontend';
import { CalendarDays, Link2, Paperclip, Pencil, Trash2 } from 'lucide-react';

/**
 * Icon-only toolbar from a journal entry header. The middle action's tooltip
 * is forced `open` so the static capture shows the real bubble; the siblings
 * stay closed, which is how the toolbar actually reads in use.
 */
export function IconAction() {
  return (
    <div
      className='flex items-center justify-center gap-1'
      style={{ paddingTop: 44 }}
    >
      <Button variant='ghost' size='icon'>
        <Pencil />
      </Button>
      <Tooltip open>
        <TooltipTrigger asChild>
          <Button variant='ghost' size='icon'>
            <Link2 />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Link this entry to a contact</TooltipContent>
      </Tooltip>
      <Button variant='ghost' size='icon'>
        <Paperclip />
      </Button>
      <Button variant='ghost' size='icon'>
        <Trash2 />
      </Button>
    </div>
  );
}

/** Side placement — the label a collapsed sidebar item shows on hover. */
export function CollapsedNavItem() {
  return (
    <div
      className='flex items-center gap-2'
      style={{ paddingTop: 60, paddingLeft: 8 }}
    >
      <Tooltip open>
        <TooltipTrigger asChild>
          <Button variant='secondary' size='icon'>
            <CalendarDays />
          </Button>
        </TooltipTrigger>
        <TooltipContent side='right'>Journals — 128 entries</TooltipContent>
      </Tooltip>
    </div>
  );
}
