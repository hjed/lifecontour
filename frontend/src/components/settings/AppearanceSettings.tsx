/**
 * AppearanceSettings: the colour palette saved on the user's account.
 *
 * Picking a palette saves it straight away — there is nothing to validate —
 * and repaints the app before the save lands. Light/dark mode is a separate,
 * per-device choice in the header's theme toggle.
 */

'use client';

import { Palette } from 'lucide-react';

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { useUpdateAppearance, useUserSettings } from '@/lib/api/settings';
import {
  DEFAULT_PALETTE,
  PALETTE_DETAILS,
  THEME_PALETTES,
  isThemePalette,
} from '@/lib/theme/palettes';
import { SettingsLoadError } from './SettingsLoadError';

export function AppearanceSettings() {
  const { data, isError } = useUserSettings();
  const { mutate: savePalette, isPending, variables } = useUpdateAppearance();

  const stored = data?.data.attributes.theme_palette;
  const persisted = isThemePalette(stored) ? stored : DEFAULT_PALETTE;
  // While a save is in flight its palette is the one on screen.
  const selected = isPending && variables ? variables : persisted;
  // Saving before the stored palette has loaded would overwrite it unseen.
  const loaded = data !== undefined;

  return (
    <Card data-testid='appearance-settings'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <Palette className='h-5 w-5' aria-hidden='true' />
          Appearance
        </CardTitle>
        <CardDescription>
          Your colour palette follows you to every device. Light or dark mode is
          set per device from the header.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        <RadioGroup
          aria-label='Colour palette'
          value={selected}
          onValueChange={value => {
            if (isThemePalette(value) && value !== selected) {
              savePalette(value);
            }
          }}
          // Locked while saving, so a quicker second pick can never be
          // overtaken by the first one's late response.
          disabled={!loaded || isPending}
          className='grid gap-3 sm:grid-cols-2'
        >
          {THEME_PALETTES.map(palette => {
            const { label, description, swatch } = PALETTE_DETAILS[palette];
            const id = `palette-${palette}`;
            return (
              <Label
                key={palette}
                htmlFor={id}
                data-testid={`palette-option-${palette}`}
                className='border-border has-[[data-state=checked]]:border-primary flex cursor-pointer items-start gap-3 rounded-lg border p-3 font-normal'
              >
                <RadioGroupItem id={id} value={palette} className='mt-0.5' />
                <span className='flex min-w-0 flex-col gap-2'>
                  <span className='font-medium'>{label}</span>
                  <span className='text-muted-foreground text-sm'>
                    {description}
                  </span>
                  <span className='flex gap-1' aria-hidden='true'>
                    {swatch.map(colour => (
                      <span
                        key={colour}
                        className='border-border size-5 rounded-full border'
                        style={{ backgroundColor: colour }}
                      />
                    ))}
                  </span>
                </span>
              </Label>
            );
          })}
        </RadioGroup>
        {isError && <SettingsLoadError />}
      </CardContent>
    </Card>
  );
}
