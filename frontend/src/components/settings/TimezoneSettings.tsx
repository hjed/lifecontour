/**
 * TimezoneSettings component for managing default timezone preference.
 *
 * Stores the user's preferred timezone in localStorage. When set, new events
 * will default to this timezone. The EventTypeEditor allows overriding per event.
 */

'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
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

const TIMEZONE_STORAGE_KEY = 'pms-default-timezone';

/**
 * Get the user's default timezone from localStorage.
 * Falls back to the browser's timezone.
 */
export function getDefaultTimezone(): string {
  if (typeof window === 'undefined') {
    return 'UTC';
  }
  const stored = localStorage.getItem(TIMEZONE_STORAGE_KEY);
  return stored || Intl.DateTimeFormat().resolvedOptions().timeZone;
}

export function TimezoneSettings() {
  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [timezone, setTimezone] = useState(browserTimezone);
  const [saved, setSaved] = useState(false);
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem(TIMEZONE_STORAGE_KEY);
    if (stored) {
      setTimezone(stored);
    }
    return () => {
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
    };
  }, []);

  const flashSaved = useCallback(() => {
    setSaved(true);
    if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
    savedTimerRef.current = setTimeout(() => setSaved(false), 2000);
  }, []);

  const handleSave = useCallback(() => {
    localStorage.setItem(TIMEZONE_STORAGE_KEY, timezone);
    flashSaved();
  }, [timezone, flashSaved]);

  const handleReset = useCallback(() => {
    localStorage.removeItem(TIMEZONE_STORAGE_KEY);
    setTimezone(browserTimezone);
    flashSaved();
  }, [browserTimezone, flashSaved]);

  return (
    <Card data-testid='timezone-settings'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <Globe className='h-5 w-5' />
          Timezone
        </CardTitle>
        <CardDescription>
          Set your default timezone for new journal events. This can be
          overridden per event in the event editor.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        <div className='space-y-2'>
          <Label htmlFor='default-timezone'>Default Timezone</Label>
          <Input
            id='default-timezone'
            value={timezone}
            onChange={e => setTimezone(e.target.value)}
            placeholder={browserTimezone}
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
            data-testid='save-timezone-btn'
          >
            {saved ? 'Saved!' : 'Save'}
          </Button>
          <Button
            onClick={handleReset}
            variant='outline'
            size='sm'
            data-testid='reset-timezone-btn'
          >
            Reset to browser
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
