/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DefaultCountrySettings } from '../DefaultCountrySettings';
import { useUpdateDefaultCountry, useUserSettings } from '@/lib/api/settings';

jest.mock('@/lib/api/settings', () => ({
  ...jest.requireActual('@/lib/api/settings'),
  useUserSettings: jest.fn(),
  useUpdateDefaultCountry: jest.fn(),
}));

const mockUseUserSettings = useUserSettings as jest.Mock;
const mockUseUpdateDefaultCountry = useUpdateDefaultCountry as jest.Mock;

function settingsWith(defaultCountry: string | null) {
  mockUseUserSettings.mockReturnValue({
    data: {
      data: {
        id: 'user-1',
        type: 'user_settings',
        attributes: { timezone: null, default_country: defaultCountry },
      },
    },
    isLoading: false,
  });
}

describe('DefaultCountrySettings', () => {
  const mockSave = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseUpdateDefaultCountry.mockReturnValue({
      mutate: mockSave,
      isPending: false,
    });
  });

  it('shows the persisted country by name', () => {
    settingsWith('NZ');

    render(<DefaultCountrySettings />);

    expect(screen.getByRole('combobox')).toHaveTextContent('New Zealand');
  });

  it('shows None when no country is set', () => {
    settingsWith(null);

    render(<DefaultCountrySettings />);

    expect(screen.getByRole('combobox')).toHaveTextContent('None');
  });

  it('saves the chosen country code', async () => {
    const user = userEvent.setup();
    settingsWith(null);
    render(<DefaultCountrySettings />);

    await user.click(screen.getByRole('combobox'));
    await user.click(screen.getByRole('option', { name: 'Australia' }));
    await user.click(screen.getByTestId('save-default-country-btn'));

    expect(mockSave).toHaveBeenCalledWith('AU');
  });

  it('clears the country when None is saved', async () => {
    const user = userEvent.setup();
    settingsWith('GB');
    render(<DefaultCountrySettings />);

    await user.click(screen.getByRole('combobox'));
    await user.click(screen.getByRole('option', { name: 'None' }));
    await user.click(screen.getByTestId('save-default-country-btn'));

    expect(mockSave).toHaveBeenCalledWith(null);
  });
});
