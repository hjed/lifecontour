import {
  Avatar,
  AvatarFallback,
  Badge,
  Button,
  Input,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Separator,
} from 'personal-management-frontend';
import { Plus, Tag } from 'lucide-react';

/**
 * "Link contact" popover — the inline editor used by JournalContactBadge.
 * `open` is forced (and `modal={false}` set) so the static capture shows the
 * real floating panel rather than a lone trigger button.
 */
export function LinkContact() {
  return (
    <div className='flex justify-center'>
      <Popover open modal={false}>
        <PopoverTrigger asChild>
          <Button variant='outline' size='sm'>
            <Plus />
            Link contact
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className='w-80'
          align='center'
          onOpenAutoFocus={e => e.preventDefault()}
        >
          <div className='flex flex-col gap-3'>
            <div className='flex flex-col gap-1'>
              <span className='text-sm font-medium'>Link a contact</span>
              <span className='text-muted-foreground text-xs'>
                Who was part of this entry?
              </span>
            </div>
            <div className='flex flex-col gap-2'>
              <Label htmlFor='contact-search'>Search contacts</Label>
              <Input id='contact-search' placeholder='Name or email…' />
            </div>
            <div className='flex flex-col gap-2'>
              <div className='flex items-center gap-2'>
                <Avatar className='h-6 w-6'>
                  <AvatarFallback className='text-xs'>PR</AvatarFallback>
                </Avatar>
                <span className='text-sm'>Priya Raman</span>
                <Badge variant='secondary' className='ml-auto'>
                  Participant
                </Badge>
              </div>
              <div className='flex items-center gap-2'>
                <Avatar className='h-6 w-6'>
                  <AvatarFallback className='text-xs'>TN</AvatarFallback>
                </Avatar>
                <span className='text-sm'>Tom Nguyen</span>
                <Badge variant='outline' className='ml-auto'>
                  Invitee
                </Badge>
              </div>
            </div>
            <Separator />
            <div className='flex justify-end gap-2'>
              <Button variant='ghost' size='sm'>
                Cancel
              </Button>
              <Button size='sm'>Link 2 contacts</Button>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

const tags = [
  { name: 'Bushwalking', count: 41 },
  { name: 'Cycling', count: 27 },
  { name: 'Family', count: 63 },
  { name: 'Favourite places', count: 12 },
];

/** Compact list popover — the tag picker opened from a journal entry header. */
export function TagPicker() {
  return (
    <div className='flex justify-center'>
      <Popover open modal={false}>
        <PopoverTrigger asChild>
          <Button variant='outline' size='sm'>
            <Tag />
            Add tag
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className='w-72 p-0'
          align='center'
          onOpenAutoFocus={e => e.preventDefault()}
        >
          <div className='border-b p-3'>
            <span className='text-sm font-medium'>Tag this entry</span>
          </div>
          <div className='flex flex-col p-1'>
            {tags.map(t => (
              <div
                key={t.name}
                className='flex items-center gap-2 rounded-md px-2 py-2 text-sm'
              >
                <Tag className='text-muted-foreground h-4 w-4' />
                {t.name}
                <span className='text-muted-foreground ml-auto text-xs'>
                  {t.count}
                </span>
              </div>
            ))}
          </div>
          <Separator />
          <div className='p-3'>
            <Button variant='ghost' size='sm' className='w-full'>
              <Plus />
              Create new tag
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
