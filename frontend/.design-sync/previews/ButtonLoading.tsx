import { Button, ButtonLoading } from 'personal-management-frontend';

export function InButtons() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Button disabled>
        <ButtonLoading text='Saving entry…' />
      </Button>
      <Button variant='secondary' disabled>
        <ButtonLoading text='Adding tag…' />
      </Button>
      <Button variant='outline' disabled>
        <ButtonLoading text='Syncing Strava…' />
      </Button>
      <Button variant='destructive' disabled>
        <ButtonLoading text='Deleting…' />
      </Button>
    </div>
  );
}

export function Sizes() {
  return (
    <div className='flex flex-wrap items-center gap-3'>
      <Button size='sm' disabled>
        <ButtonLoading text='Saving…' />
      </Button>
      <Button disabled>
        <ButtonLoading text='Saving…' />
      </Button>
      <Button size='lg' disabled>
        <ButtonLoading text='Saving…' />
      </Button>
    </div>
  );
}

export function Standalone() {
  return (
    <div className='space-y-3 text-sm'>
      <ButtonLoading />
      <ButtonLoading text='Importing 1,284 journal entries…' />
      <ButtonLoading text='Uploading photos to Immich…' />
    </div>
  );
}
