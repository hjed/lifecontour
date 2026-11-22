'use client';

/**
 * Applies the signed-in user's colour palette to <html>.
 *
 * The blocking <head> script has already painted the cached palette by the
 * time this mounts, so until the settings read lands nothing changes. Once it
 * does, the account is the answer — including `null`, which is the default
 * palette — and the localStorage mirror follows it for the next first paint.
 * Signed out, the settings are not read at all (AuthProvider resets the
 * palette then).
 */

import { useEffect } from 'react';

import { useUserSettings } from '@/lib/api/settings';
import { useAuth } from '@/lib/auth/AuthProvider';
import {
  DEFAULT_PALETTE,
  applyPalette,
  cachePalette,
  isThemePalette,
} from '@/lib/theme/palettes';

interface PaletteProviderProps {
  children: React.ReactNode;
}

export function PaletteProvider({ children }: PaletteProviderProps) {
  const { state } = useAuth();
  const { data } = useUserSettings({ enabled: state.isAuthenticated });
  const stored = data?.data.attributes.theme_palette;
  // `undefined` = no read yet; anything else is the account's answer.
  const palette =
    stored === undefined
      ? undefined
      : isThemePalette(stored)
        ? stored
        : DEFAULT_PALETTE;

  useEffect(() => {
    if (palette === undefined) {
      return;
    }
    applyPalette(palette);
    cachePalette(palette);
  }, [palette]);

  return <>{children}</>;
}
