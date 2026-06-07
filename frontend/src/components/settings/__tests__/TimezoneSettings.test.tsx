/**
 * @jest-environment jsdom
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TimezoneSettings, getDefaultTimezone } from '../TimezoneSettings';
import { useUpdateTimezone, useUserSettings } from '@/lib/api/settings';

jest.mock('@/lib/api/settings', () => ({
  ...jest.requireActual('@/lib/api/settings'),
  useUserSettings: jest.fn(),
  useUpdateTimezone: jest.fn(),
}));

const mockUseUserSettings = useUserSettings as jest.Mock;
const mockUseUpdateTimezone = useUpdateTimezone as jest.Mock;

describe('TimezoneSettings', () => {
  const mockSave = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();

    mockUseUserSettings.mockReturnValue({
      data: {
        data: {
          id: 'user-1',
          type: 'user_settings',
          attributes: { timezone: 'Australia/Sydney' },
        },
      },
      isLoading: false,
    });

    mockUseUpdateTimezone.mockReturnValue({
      mutate: mockSave,
      isPending: false,
    });
  });

  it('seeds the input from the persisted timezone', async () => {
    render(<TimezoneSettings />);

    await waitFor(() => {
      expect(
        (screen.getByTestId('default-timezone-input') as HTMLInputElement).value
      ).toBe('Australia/Sydney');
    });
  });

  it('caches the persisted timezone in localStorage', async () => {
    render(<TimezoneSettings />);

    await waitFor(() => {
      expect(getDefaultTimezone()).toBe('Australia/Sydney');
    });
  });

  it('saves the edited timezone to the backend', async () => {
    render(<TimezoneSettings />);

    await waitFor(() => {
      expect(
        (screen.getByTestId('default-timezone-input') as HTMLInputElement).value
      ).toBe('Australia/Sydney');
    });

    fireEvent.change(screen.getByTestId('default-timezone-input'), {
      target: { value: 'America/New_York' },
    });
    fireEvent.click(screen.getByTestId('save-timezone-btn'));

    expect(mockSave).toHaveBeenCalledWith('America/New_York');
  });
});
