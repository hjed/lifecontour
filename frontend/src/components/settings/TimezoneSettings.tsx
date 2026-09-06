/**
 * TimezoneSettings component for managing the default timezone preference.
 *
 * The timezone is persisted on the backend (so server-side AI prompt
 * generation can render dates/times in the user's local time) and mirrored
 * into localStorage as a cache. New events default to this timezone via
 * {@link getDefaultTimezone}; the EventTypeEditor allows overriding per event.
 */

'use client';

import { useEffect, useState } from 'react';
import { Globe } from 'lucide-react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import {
  getBrowserTimezone,
  getDefaultTimezone,
  TIMEZONE_STORAGE_KEY,
  useUpdateTimezone,
  useUserSettings,
} from '@/lib/api/settings';

/**
 * Re-exported from the API layer, where it has to live: `lib/` reaches for it
 * too, and `lib/` importing a `'use client'` component would pull Card, Input
 * and Button into every module that wanted the timezone.
 */
export { getDefaultTimezone };

export function TimezoneSettings() {
  const browserTimezone = getBrowserTimezone();
  const { data, isLoading } = useUserSettings();
  const { mutate: saveTimezone, isPending } = useUpdateTimezone();

  // The displayed value is the user's edit (draft) if any, otherwise the
  // persisted value, otherwise the browser timezone. Deriving it avoids
  // syncing query data into state via an effect.
  const persisted = data?.data.attributes.timezone;
  const [draft, setDraft] = useState<string | null>(null);
  const timezone = draft ?? persisted ?? browserTimezone;

  // Mirror the persisted value into the localStorage cache so the synchronous
  // getDefaultTimezone() helper stays current. Writes only — no state update.
  useEffect(() => {
    if (persisted) {
      localStorage.setItem(TIMEZONE_STORAGE_KEY, persisted);
    }
  }, [persisted]);

  const handleSave = () => {
    saveTimezone(timezone);
  };

  const handleReset = () => {
    setDraft(browserTimezone);
    saveTimezone(browserTimezone);
  };

  return (
    <Card data-testid='timezone-settings'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <Globe className='h-5 w-5' />
          Timezone
        </CardTitle>
        <CardDescription>
          Set your default timezone. It is used for new journal events and so
          AI-generated summaries show times in your local timezone. This can be
          overridden per event in the event editor.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        <div className='space-y-2'>
          <Label htmlFor='default-timezone'>Default Timezone</Label>
          <Input
            id='default-timezone'
            value={timezone}
            onChange={e => setDraft(e.target.value)}
            placeholder={browserTimezone}
            disabled={isLoading}
            data-testid='default-timezone-input'
          />
          {timezone !== browserTimezone && (
            <p className='text-muted-foreground text-xs'>
              Browser timezone: {browserTimezone}
            </p>
          )}
        </div>
        <div className='flex gap-2'>
          <Button
            onClick={handleSave}
            size='sm'
            disabled={isPending || isLoading}
            data-testid='save-timezone-btn'
          >
            {isPending ? 'Saving…' : 'Save'}
          </Button>
          <Button
            onClick={handleReset}
            variant='outline'
            size='sm'
            disabled={isPending || isLoading}
            data-testid='reset-timezone-btn'
          >
            Reset to browser
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
