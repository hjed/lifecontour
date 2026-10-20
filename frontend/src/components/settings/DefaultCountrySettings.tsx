/**
 * DefaultCountrySettings component for the country filled in for imported
 * addresses that have none.
 *
 * A Google contact address without a country is given the contact's primary
 * phone country, else the country all its phones agree on, else this one;
 * with none of them it is not imported (#1820).
 */

'use client';

import { useMemo, useState } from 'react';
import { MapPin } from 'lucide-react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useUpdateDefaultCountry, useUserSettings } from '@/lib/api/settings';
import { listCountries } from '@/lib/countries';

/** Radix Select reserves `''`, so "no country" needs a value of its own. */
const NO_COUNTRY = 'none';

export function DefaultCountrySettings() {
  const { data, isLoading } = useUserSettings();
  const { mutate: saveDefaultCountry, isPending } = useUpdateDefaultCountry();
  const countries = useMemo(() => listCountries(), []);

  // The user's pick if any, otherwise the persisted value — derived rather
  // than synced from the query into state.
  const persisted = data?.data.attributes.default_country ?? null;
  const [draft, setDraft] = useState<string | null>(null);
  const selected = draft ?? persisted ?? NO_COUNTRY;

  const handleSave = () => {
    saveDefaultCountry(selected === NO_COUNTRY ? null : selected);
  };

  return (
    <Card data-testid='default-country-settings'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <MapPin className='h-5 w-5' />
          Default Country
        </CardTitle>
        <CardDescription>
          Used for imported contact addresses that have no country, when the
          contact&apos;s phone numbers don&apos;t give one. Contacts already
          imported pick it up the next time they change in Google.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        <div className='space-y-2'>
          <Label htmlFor='default-country'>Country</Label>
          <Select
            value={selected}
            onValueChange={setDraft}
            disabled={isLoading}
          >
            <SelectTrigger
              id='default-country'
              data-testid='default-country-select'
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_COUNTRY}>None</SelectItem>
              {countries.map(country => (
                <SelectItem key={country.code} value={country.code}>
                  {country.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          onClick={handleSave}
          size='sm'
          disabled={isPending || isLoading}
          data-testid='save-default-country-btn'
        >
          {isPending ? 'Saving…' : 'Save'}
        </Button>
      </CardContent>
    </Card>
  );
}
