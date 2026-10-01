import { Toggle } from 'lifecontour-frontend';
import { Bold, Italic, List, Pin, Star } from 'lucide-react';

export function Variants() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Toggle aria-label='Favourite'>Default off</Toggle>
      <Toggle defaultPressed aria-label='Favourite'>
        Default on
      </Toggle>
      <Toggle variant='outline' aria-label='Pinned'>
        Outline off
      </Toggle>
      <Toggle variant='outline' defaultPressed aria-label='Pinned'>
        Outline on
      </Toggle>
    </div>
  );
}

export function Sizes() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Toggle variant='outline' size='sm' defaultPressed>
        Small
      </Toggle>
      <Toggle variant='outline' size='default' defaultPressed>
        Default
      </Toggle>
      <Toggle variant='outline' size='lg' defaultPressed>
        Large
      </Toggle>
    </div>
  );
}

export function IconOnly() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Toggle defaultPressed aria-label='Bold'>
        <Bold />
      </Toggle>
      <Toggle aria-label='Italic'>
        <Italic />
      </Toggle>
      <Toggle aria-label='Bullet list'>
        <List />
      </Toggle>
      <Toggle variant='outline' defaultPressed aria-label='Favourite contact'>
        <Star />
      </Toggle>
      <Toggle variant='outline' aria-label='Pin entry'>
        <Pin />
      </Toggle>
    </div>
  );
}

export function WithLabelAndDisabled() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Toggle variant='outline' defaultPressed>
        <Star />
        Favourites
      </Toggle>
      <Toggle variant='outline'>
        <Pin />
        Pinned
      </Toggle>
      <Toggle variant='outline' disabled>
        <List />
        Archived
      </Toggle>
    </div>
  );
}
