import {
  Avatar,
  AvatarFallback,
  Badge,
  Button,
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
  Separator,
} from 'personal-management-frontend';
import { CalendarDays, MapPin } from 'lucide-react';

/**
 * Contact peek — hovering a contact mention inside a journal entry.
 * `open` is forced so the static capture shows the card, not just the link.
 */
export function ContactPreview() {
  return (
    <div className='flex justify-center'>
      <HoverCard open>
        <HoverCardTrigger asChild>
          <Button variant='link' className='px-0'>
            @Priya Raman
          </Button>
        </HoverCardTrigger>
        <HoverCardContent className='w-80' align='center'>
          <div className='flex gap-3'>
            <Avatar className='h-10 w-10'>
              <AvatarFallback>PR</AvatarFallback>
            </Avatar>
            <div className='flex flex-col gap-1'>
              <span className='text-sm font-semibold'>Priya Raman</span>
              <span className='text-muted-foreground text-sm'>
                Trail running friend — met through the Tuesday night group.
              </span>
              <div className='mt-1 flex flex-wrap gap-1'>
                <Badge variant='secondary'>Bushwalking</Badge>
                <Badge variant='secondary'>Running</Badge>
              </div>
              <div className='text-muted-foreground mt-2 flex items-center gap-2 text-xs'>
                <MapPin className='h-3 w-3' />
                Northcote, VIC
              </div>
              <div className='text-muted-foreground flex items-center gap-2 text-xs'>
                <CalendarDays className='h-3 w-3' />
                Last catch-up 14 July 2026
              </div>
            </div>
          </div>
        </HoverCardContent>
      </HoverCard>
    </div>
  );
}

/** Definition peek — hovering a tag chip to see what it covers. */
export function TagSummary() {
  return (
    <div className='flex justify-center'>
      <HoverCard open>
        <HoverCardTrigger asChild>
          <Button variant='secondary' size='sm'>
            Bushwalking
          </Button>
        </HoverCardTrigger>
        <HoverCardContent className='w-72' align='center'>
          <div className='flex flex-col gap-2'>
            <span className='text-sm font-semibold'>Bushwalking</span>
            <span className='text-muted-foreground text-sm'>
              Day walks and overnight hikes, mostly around the Grampians and the
              Otways.
            </span>
            <Separator />
            <div className='text-muted-foreground flex items-center justify-between text-xs'>
              <span>41 journal entries</span>
              <span>Added 3 March 2024</span>
            </div>
          </div>
        </HoverCardContent>
      </HoverCard>
    </div>
  );
}
