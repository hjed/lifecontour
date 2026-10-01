import { Label, Switch } from 'lifecontour-frontend';

export function States() {
  return (
    <div className='flex max-w-sm flex-col gap-4'>
      <div className='flex items-center gap-2'>
        <Switch id='switch-off' />
        <Label htmlFor='switch-off'>Off</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Switch id='switch-on' defaultChecked />
        <Label htmlFor='switch-on'>On</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Switch id='switch-disabled' disabled />
        <Label htmlFor='switch-disabled'>Disabled</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Switch id='switch-disabled-on' disabled defaultChecked />
        <Label htmlFor='switch-disabled-on'>Disabled and on</Label>
      </div>
    </div>
  );
}

export function SettingsRows() {
  return (
    <div className='flex max-w-md flex-col gap-4'>
      <div className='flex items-center justify-between gap-4'>
        <div className='flex flex-col gap-2'>
          <Label htmlFor='setting-strava'>Strava sync</Label>
          <p className='text-muted-foreground text-sm'>
            Import runs and rides as outdoor activity entries.
          </p>
        </div>
        <Switch id='setting-strava' defaultChecked />
      </div>
      <div className='flex items-center justify-between gap-4'>
        <div className='flex flex-col gap-2'>
          <Label htmlFor='setting-immich'>Immich photos</Label>
          <p className='text-muted-foreground text-sm'>
            Attach photos taken on the same day as an entry.
          </p>
        </div>
        <Switch id='setting-immich' defaultChecked />
      </div>
      <div className='flex items-center justify-between gap-4'>
        <div className='flex flex-col gap-2'>
          <Label htmlFor='setting-digest'>Weekly digest</Label>
          <p className='text-muted-foreground text-sm'>
            Emailed every Sunday evening, Melbourne time.
          </p>
        </div>
        <Switch id='setting-digest' />
      </div>
    </div>
  );
}

export function Inline() {
  return (
    <div className='flex max-w-sm flex-col gap-4'>
      <div className='flex items-center gap-2'>
        <Switch id='show-archived' />
        <Label htmlFor='show-archived'>Show archived contacts</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Switch id='favourites-only' defaultChecked />
        <Label htmlFor='favourites-only'>Favourites only</Label>
      </div>
    </div>
  );
}
