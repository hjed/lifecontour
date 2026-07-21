import {
  Checkbox,
  Input,
  Label,
  Switch,
  Textarea,
} from 'personal-management-frontend';
import { Lock } from 'lucide-react';

export function WithInput() {
  return (
    <div className='flex max-w-sm flex-col gap-4'>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='contact-name'>Full name</Label>
        <Input id='contact-name' defaultValue='Priya Raman' />
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='contact-note'>Note</Label>
        <Textarea
          id='contact-note'
          rows={2}
          defaultValue='Prefers a phone call over email.'
        />
      </div>
    </div>
  );
}

export function WithControls() {
  return (
    <div className='flex max-w-sm flex-col gap-4'>
      <div className='flex items-center gap-2'>
        <Checkbox id='favourite-contact' defaultChecked />
        <Label htmlFor='favourite-contact'>Mark as favourite</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Switch id='weekly-digest' defaultChecked />
        <Label htmlFor='weekly-digest'>Email me a weekly digest</Label>
      </div>
    </div>
  );
}

export function WithIconAndHint() {
  return (
    <div className='flex max-w-sm flex-col gap-2'>
      <Label htmlFor='private-entry'>
        <Lock aria-hidden='true' className='size-4' />
        Private entry key
      </Label>
      <Input id='private-entry' defaultValue='journal-2026-07-14' />
      <p className='text-muted-foreground text-sm'>
        Labels are flex containers, so leading icons align automatically.
      </p>
    </div>
  );
}

export function DisabledPeer() {
  return (
    <div className='flex max-w-sm flex-col gap-4'>
      <div className='flex items-center gap-2'>
        <Checkbox id='sync-immich' disabled className='peer' />
        <Label htmlFor='sync-immich'>Sync photos from Immich</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Checkbox id='sync-strava' disabled defaultChecked className='peer' />
        <Label htmlFor='sync-strava'>Sync activities from Strava</Label>
      </div>
      <div className='flex items-center gap-2'>
        <Switch id='sync-nightly' disabled className='peer' />
        <Label htmlFor='sync-nightly'>Run the nightly reconcile</Label>
      </div>
      <p className='text-muted-foreground text-sm'>
        A label dims itself when the control it follows is disabled.
      </p>
    </div>
  );
}
