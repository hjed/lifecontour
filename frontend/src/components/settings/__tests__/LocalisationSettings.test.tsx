/**
 * @jest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LocalisationSettings } from '../LocalisationSettings';
import {
  getBrowserTimezone,
  getDefaultTimezone,
  useUpdateLocalisation,
  useUserSettings,
} from '@/lib/api/settings';

jest.mock('@/lib/api/settings', () => ({
  ...jest.requireActual('@/lib/api/settings'),
  useUserSettings: jest.fn(),
  useUpdateLocalisation: jest.fn(),
}));

const mockUseUserSettings = useUserSettings as jest.Mock;
const mockUseUpdateLocalisation = useUpdateLocalisation as jest.Mock;

function settingsWith(timezone: string | null, defaultCountry: string | null) {
  mockUseUserSettings.mockReturnValue({
    data: {
      data: {
        id: 'user-1',
        type: 'user_settings',
        attributes: { timezone, default_country: defaultCountry },
      },
    },
    isLoading: false,
  });
}

function timezoneInput(): HTMLInputElement {
  return screen.getByTestId('default-timezone-input') as HTMLInputElement;
}

describe('LocalisationSettings', () => {
  const mockSave = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    mockUseUpdateLocalisation.mockReturnValue({
      mutate: mockSave,
      isPending: false,
    });
  });

  it('shows the persisted timezone and country', () => {
    settingsWith('Australia/Sydney', 'NZ');

    render(<LocalisationSettings />);

    expect(timezoneInput().value).toBe('Australia/Sydney');
    expect(screen.getByRole('combobox')).toHaveTextContent('New Zealand');
  });

  it('falls back to the browser timezone and None when nothing is set', () => {
    settingsWith(null, null);

    render(<LocalisationSettings />);

    expect(timezoneInput().value).toBe(getBrowserTimezone());
    expect(screen.getByRole('combobox')).toHaveTextContent('None');
  });

  it('caches the persisted timezone in localStorage', async () => {
    settingsWith('Australia/Sydney', null);

    render(<LocalisationSettings />);

    await waitFor(() => {
      expect(getDefaultTimezone()).toBe('Australia/Sydney');
    });
  });

  it('saves the timezone and country together', async () => {
    const user = userEvent.setup();
    settingsWith('Australia/Sydney', null);
    render(<LocalisationSettings />);

    fireEvent.change(timezoneInput(), {
      target: { value: 'America/New_York' },
    });
    await user.click(screen.getByRole('combobox'));
    await user.click(screen.getByRole('option', { name: 'Australia' }));
    await user.click(screen.getByTestId('save-localisation-btn'));

    expect(mockSave).toHaveBeenCalledWith({
      timezone: 'America/New_York',
      default_country: 'AU',
    });
  });

  it('clears the country when None is saved', async () => {
    const user = userEvent.setup();
    settingsWith('Australia/Sydney', 'GB');
    render(<LocalisationSettings />);

    await user.click(screen.getByRole('combobox'));
    await user.click(screen.getByRole('option', { name: 'None' }));
    await user.click(screen.getByTestId('save-localisation-btn'));

    expect(mockSave).toHaveBeenCalledWith({ default_country: null });
  });

  it('leaves an unset timezone unset when only the country is saved', async () => {
    const user = userEvent.setup();
    settingsWith(null, null);
    render(<LocalisationSettings />);

    await user.click(screen.getByRole('combobox'));
    await user.click(screen.getByRole('option', { name: 'New Zealand' }));
    await user.click(screen.getByTestId('save-localisation-btn'));

    expect(mockSave).toHaveBeenCalledWith({ default_country: 'NZ' });
  });

  it('resets the timezone to the browser without saving', async () => {
    const user = userEvent.setup();
    settingsWith('Pacific/Chatham', null);
    render(<LocalisationSettings />);

    await user.click(screen.getByTestId('reset-timezone-btn'));

    expect(timezoneInput().value).toBe(getBrowserTimezone());
    expect(mockSave).not.toHaveBeenCalled();
  });

  it('keeps Save and Reset disabled when the settings could not be loaded', () => {
    mockUseUserSettings.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    });

    render(<LocalisationSettings />);

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Could not load your settings'
    );
    expect(screen.getByTestId('save-localisation-btn')).toBeDisabled();
    expect(screen.getByTestId('reset-timezone-btn')).toBeDisabled();
  });
});
