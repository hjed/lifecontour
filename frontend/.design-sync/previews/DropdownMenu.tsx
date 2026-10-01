import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from 'lifecontour-frontend';
import {
  ChevronDown,
  Download,
  FolderPlus,
  Pencil,
  SlidersHorizontal,
  Tag,
  Trash2,
  UserPlus,
} from 'lucide-react';

/**
 * Row actions for a journal entry. Forced `open` with `modal={false}` so the
 * static capture photographs the menu itself instead of the trigger button.
 */
export function EntryActions() {
  return (
    <div className='flex justify-center'>
      <DropdownMenu open modal={false}>
        <DropdownMenuTrigger asChild>
          <Button variant='outline' size='sm'>
            Actions
            <ChevronDown />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className='w-56' align='center'>
          <DropdownMenuLabel>Morning run</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem>
              <Pencil />
              Edit entry
              <DropdownMenuShortcut>⌘E</DropdownMenuShortcut>
            </DropdownMenuItem>
            <DropdownMenuItem>
              <Tag />
              Add tag
            </DropdownMenuItem>
            <DropdownMenuItem>
              <UserPlus />
              Link to contact
            </DropdownMenuItem>
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <FolderPlus className='mr-2 h-4 w-4' />
                Add to series
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                <DropdownMenuItem>Weekly long run</DropdownMenuItem>
                <DropdownMenuItem>Grampians 2026</DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem>
            <Download />
            Export logbook PDF
            <DropdownMenuShortcut>⇧⌘P</DropdownMenuShortcut>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant='destructive'>
            <Trash2 />
            Delete journal
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

/** Checkbox and radio items — the journal list's view options menu. */
export function ViewOptions() {
  return (
    <div className='flex justify-center'>
      <DropdownMenu open modal={false}>
        <DropdownMenuTrigger asChild>
          <Button variant='outline' size='sm'>
            <SlidersHorizontal />
            View
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className='w-56' align='center'>
          <DropdownMenuLabel>Show columns</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuCheckboxItem checked>Tags</DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem checked>Contacts</DropdownMenuCheckboxItem>
          <DropdownMenuCheckboxItem>Calendar source</DropdownMenuCheckboxItem>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Sort by</DropdownMenuLabel>
          <DropdownMenuRadioGroup value='newest'>
            <DropdownMenuRadioItem value='newest'>
              Newest first
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value='oldest'>
              Oldest first
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value='title'>
              Title A–Z
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
