/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AppearanceSettings } from '../AppearanceSettings';
import { useUpdateAppearance, useUserSettings } from '@/lib/api/settings';

jest.mock('@/lib/api/settings', () => ({
  ...jest.requireActual('@/lib/api/settings'),
  useUserSettings: jest.fn(),
  useUpdateAppearance: jest.fn(),
}));

const mockUseUserSettings = useUserSettings as jest.Mock;
const mockUseUpdateAppearance = useUpdateAppearance as jest.Mock;

function settingsWith(themePalette: string | null | undefined) {
  mockUseUserSettings.mockReturnValue({
    data:
      themePalette === undefined
        ? undefined
        : {
            data: {
              id: 'user-1',
              type: 'user_settings',
              attributes: {
                timezone: null,
                default_country: null,
                theme_palette: themePalette,
              },
            },
          },
    isError: false,
  });
}

function option(name: RegExp) {
  return screen.getByRole('radio', { name });
}

describe('AppearanceSettings', () => {
  const mockSave = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseUpdateAppearance.mockReturnValue({
      mutate: mockSave,
      isPending: false,
      variables: undefined,
    });
  });

  it('offers every palette the app ships', () => {
    settingsWith(null);

    render(<AppearanceSettings />);

    expect(option(/default/i)).toBeInTheDocument();
    expect(option(/emerald/i)).toBeInTheDocument();
  });

  it('checks the default palette when none is chosen', () => {
    settingsWith(null);

    render(<AppearanceSettings />);

    expect(option(/default/i)).toBeChecked();
    expect(option(/emerald/i)).not.toBeChecked();
  });

  it('checks the palette saved on the account', () => {
    settingsWith('emerald');

    render(<AppearanceSettings />);

    expect(option(/emerald/i)).toBeChecked();
  });

  it('saves a palette as soon as it is picked', async () => {
    const user = userEvent.setup();
    settingsWith(null);

    render(<AppearanceSettings />);
    await user.click(option(/emerald/i));

    expect(mockSave).toHaveBeenCalledWith('emerald');
  });

  it('shows the palette being saved while the save is in flight', () => {
    settingsWith(null);
    mockUseUpdateAppearance.mockReturnValue({
      mutate: mockSave,
      isPending: true,
      variables: 'emerald',
    });

    render(<AppearanceSettings />);

    expect(option(/emerald/i)).toBeChecked();
  });

  it('is locked while a save is in flight so saves cannot overtake', () => {
    settingsWith(null);
    mockUseUpdateAppearance.mockReturnValue({
      mutate: mockSave,
      isPending: true,
      variables: 'emerald',
    });

    render(<AppearanceSettings />);

    expect(option(/default/i)).toBeDisabled();
    expect(option(/emerald/i)).toBeDisabled();
  });

  it('cannot be changed before the saved palette has loaded', () => {
    settingsWith(undefined);

    render(<AppearanceSettings />);

    expect(option(/emerald/i)).toBeDisabled();
  });
});
