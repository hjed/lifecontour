/** @jest-environment jsdom */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SnipeItSettings } from '../SnipeItSettings';
import {
  useSnipeItSettings,
  useSaveSnipeItSettings,
  useSnipeItConnect,
  useSnipeItDisconnect,
} from '@/lib/api/integrations';
import { APP_NAME } from '@/lib/constants';

jest.mock('@/lib/api/integrations', () => ({
  useSnipeItSettings: jest.fn(),
  useSaveSnipeItSettings: jest.fn(),
  useSnipeItConnect: jest.fn(),
  useSnipeItDisconnect: jest.fn(),
}));

const saveMutate = jest.fn();
const connectMutate = jest.fn();
const disconnectMutate = jest.fn();

function mockSettingsQuery(
  overrides: Partial<{
    data: unknown;
    isLoading: boolean;
    isError: boolean;
    error: unknown;
  }> = {}
) {
  (useSnipeItSettings as jest.Mock).mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    ...overrides,
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockSettingsQuery();
  (useSaveSnipeItSettings as jest.Mock).mockReturnValue({
    mutate: saveMutate,
    isPending: false,
  });
  (useSnipeItConnect as jest.Mock).mockReturnValue({
    mutate: connectMutate,
    isPending: false,
  });
  (useSnipeItDisconnect as jest.Mock).mockReturnValue({
    mutate: disconnectMutate,
    isPending: false,
  });
});

describe('SnipeItSettings', () => {
  it('shows a loading state while settings are loading', () => {
    mockSettingsQuery({ isLoading: true });
    render(<SnipeItSettings />);
    expect(screen.getByText(/loading settings/i)).toBeInTheDocument();
  });

  describe('disconnected (form) state', () => {
    it('renders base URL, user ID, and API key fields with the Save & Connect button', () => {
      render(<SnipeItSettings />);

      expect(screen.getByTestId('snipeit-settings-form')).toBeInTheDocument();
      expect(screen.getByTestId('snipeit-base-url-input')).toBeInTheDocument();
      expect(screen.getByTestId('snipeit-user-id-input')).toBeInTheDocument();
      expect(screen.getByTestId('snipeit-api-key-input')).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /save & connect/i })
      ).toBeInTheDocument();
    });

    it('names the product in the user ID description', () => {
      render(<SnipeItSettings />);

      const description = screen.getByText(/your user id in snipe-it/i);
      expect(description).toHaveTextContent(`maps your ${APP_NAME} account`);
      expect(description).not.toHaveTextContent(/\bPMS\b/);
    });

    it('shows a validation error when the base URL is invalid', async () => {
      render(<SnipeItSettings />);

      fireEvent.change(screen.getByTestId('snipeit-base-url-input'), {
        target: { value: 'not-a-valid-url' },
      });
      fireEvent.click(screen.getByTestId('snipeit-settings-save-button'));

      expect(
        await screen.findByText(/must be a valid url/i)
      ).toBeInTheDocument();
      expect(saveMutate).not.toHaveBeenCalled();
    });

    it('saves base URL with a null user ID when none is provided', async () => {
      render(<SnipeItSettings />);

      fireEvent.change(screen.getByTestId('snipeit-base-url-input'), {
        target: { value: 'https://snipeit.example.com' },
      });
      fireEvent.click(screen.getByTestId('snipeit-settings-save-button'));

      await waitFor(() => {
        expect(saveMutate).toHaveBeenCalledWith(
          { base_url: 'https://snipeit.example.com', snipeit_user_id: null },
          expect.objectContaining({ onSuccess: expect.any(Function) })
        );
      });
    });

    it('pre-populates the form from loaded settings', async () => {
      mockSettingsQuery({
        data: {
          base_url: 'https://existing.example.com',
          snipeit_user_id: '42',
        },
      });
      render(<SnipeItSettings />);

      await waitFor(() => {
        expect(screen.getByTestId('snipeit-base-url-input')).toHaveValue(
          'https://existing.example.com'
        );
      });
      expect(screen.getByTestId('snipeit-user-id-input')).toHaveValue('42');
    });
  });

  describe('connected state', () => {
    it('shows Save Settings, disconnect, and update-api-key controls and hides the API key field', () => {
      render(<SnipeItSettings connected />);

      expect(
        screen.getByRole('button', { name: /save settings/i })
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('snipeit-disconnect-button')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('snipeit-update-api-key-button')
      ).toBeInTheDocument();
      // API key field is hidden until "Update API Key" is clicked
      expect(
        screen.queryByTestId('snipeit-api-key-input')
      ).not.toBeInTheDocument();
    });

    it('reveals the API key field when Update API Key is clicked', () => {
      render(<SnipeItSettings connected />);

      fireEvent.click(screen.getByTestId('snipeit-update-api-key-button'));
      expect(screen.getByTestId('snipeit-api-key-input')).toBeInTheDocument();
    });

    it('calls the disconnect mutation when the disconnect button is clicked', () => {
      render(<SnipeItSettings connected />);

      fireEvent.click(screen.getByTestId('snipeit-disconnect-button'));
      expect(disconnectMutate).toHaveBeenCalledTimes(1);
    });
  });
});
