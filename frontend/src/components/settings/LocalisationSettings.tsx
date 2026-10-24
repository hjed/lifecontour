/**
 * LocalisationSettings component for the user's default timezone and default
 * country, saved together.
 *
 * The timezone is persisted on the backend (so server-side AI prompt
 * generation can render dates/times in the user's local time) and mirrored
 * into localStorage as a cache. New events default to this timezone via
 * {@link getDefaultTimezone}; the EventTypeEditor allows overriding per event.
 *
 * The country is filled in for imported addresses that have none: a Google
 * contact address without a country is given the contact's primary phone
 * country, else the country all its phones agree on, else this one; with none
 * of them it is not imported (#1820).
 */

'use client';

import { useEffect, useMemo, useState } from 'react';
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  getBrowserTimezone,
  TIMEZONE_STORAGE_KEY,
  useUpdateLocalisation,
  useUserSettings,
} from '@/lib/api/settings';
import { listCountries } from '@/lib/countries';
import type { UserSettingsPatch } from '@/types/settings';
import { SettingsLoadError } from './SettingsLoadError';

/** Radix Select reserves `''`, so "no country" needs a value of its own. */
const NO_COUNTRY = 'none';

export function LocalisationSettings() {
  const browserTimezone = getBrowserTimezone();
  const { data, isError } = useUserSettings();
  const { mutate: saveLocalisation, isPending } = useUpdateLocalisation();
  const countries = useMemo(() => listCountries(), []);

  // Each displayed value is the user's edit (draft) if any, otherwise the
  // persisted value, otherwise its fallback. Deriving them avoids syncing
  // query data into state via an effect.
  const attributes = data?.data.attributes;
  const persistedTimezone = attributes?.timezone;
  const [timezoneDraft, setTimezoneDraft] = useState<string | null>(null);
  const timezone = timezoneDraft ?? persistedTimezone ?? browserTimezone;

  const persistedCountry = attributes?.default_country ?? null;
  const [countryDraft, setCountryDraft] = useState<string | null>(null);
  const country = countryDraft ?? persistedCountry ?? NO_COUNTRY;

  // Saving before the stored values have loaded would overwrite them unseen —
  // the browser's zone and "None" stand in for values the card never showed.
  const loaded = data !== undefined;

  // Mirror the persisted value into the localStorage cache so the synchronous
  // getDefaultTimezone() helper stays current. Writes only — no state update.
  useEffect(() => {
    if (persistedTimezone) {
      localStorage.setItem(TIMEZONE_STORAGE_KEY, persistedTimezone);
    }
  }, [persistedTimezone]);

  // Only the fields the user edited are sent. In particular a timezone they
  // never chose stays unset rather than becoming the browser's zone for good —
  // it cannot be cleared again (issue #1401).
  const handleSave = () => {
    const patch: UserSettingsPatch = {};
    if (timezoneDraft !== null) {
      patch.timezone = timezoneDraft;
    }
    if (countryDraft !== null) {
      patch.default_country = countryDraft === NO_COUNTRY ? null : countryDraft;
    }
    saveLocalisation(patch);
  };

  return (
    <Card data-testid='localisation-settings'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <Globe className='h-5 w-5' />
          Localisation
        </CardTitle>
        <CardDescription>Your default timezone and country.</CardDescription>
      </CardHeader>
      <CardContent className='space-y-6'>
        <div className='space-y-2'>
          <Label htmlFor='default-timezone'>Default Timezone</Label>
          <p className='text-muted-foreground text-sm'>
            Used for new journal events and so AI-generated summaries show times
            in your local timezone. This can be overridden per event in the
            event editor.
          </p>
          <div className='flex gap-2'>
            <Input
              id='default-timezone'
              value={timezone}
              onChange={e => setTimezoneDraft(e.target.value)}
              placeholder={browserTimezone}
              disabled={!loaded}
              data-testid='default-timezone-input'
            />
            <Button
              onClick={() => setTimezoneDraft(browserTimezone)}
              variant='outline'
              disabled={isPending || !loaded}
              data-testid='reset-timezone-btn'
            >
              Reset to browser
            </Button>
          </div>
          {timezone !== browserTimezone && (
            <p className='text-muted-foreground text-xs'>
              Browser timezone: {browserTimezone}
            </p>
          )}
        </div>
        <div className='space-y-2'>
          <Label htmlFor='default-country'>Default Country</Label>
          <p className='text-muted-foreground text-sm'>
            Used for imported contact addresses that have no country, when the
            contact&apos;s phone numbers don&apos;t give one. Contacts already
            imported pick it up the next time they change in Google.
          </p>
          <Select
            value={country}
            onValueChange={setCountryDraft}
            disabled={!loaded}
          >
            <SelectTrigger
              id='default-country'
              data-testid='default-country-select'
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_COUNTRY}>None</SelectItem>
              {countries.map(option => (
                <SelectItem key={option.code} value={option.code}>
                  {option.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {isError && <SettingsLoadError />}
        <Button
          onClick={handleSave}
          size='sm'
          disabled={isPending || !loaded}
          data-testid='save-localisation-btn'
        >
          {isPending ? 'Saving…' : 'Save'}
        </Button>
      </CardContent>
    </Card>
  );
}
