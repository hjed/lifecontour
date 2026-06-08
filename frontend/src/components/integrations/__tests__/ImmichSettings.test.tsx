/** @jest-environment jsdom */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ImmichSettings } from '../ImmichSettings';
import { useImmichConnect, useImmichDisconnect } from '@/lib/api/integrations';

jest.mock('@/lib/api/integrations', () => ({
  useImmichConnect: jest.fn(),
  useImmichDisconnect: jest.fn(),
}));

const connectMutate = jest.fn();
const disconnectMutate = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  (useImmichConnect as jest.Mock).mockReturnValue({
    mutate: connectMutate,
    isPending: false,
  });
  (useImmichDisconnect as jest.Mock).mockReturnValue({
    mutate: disconnectMutate,
    isPending: false,
  });
});

describe('ImmichSettings', () => {
  describe('disconnected (form) state', () => {
    it('renders the server URL and API key fields and the connect button', () => {
      render(<ImmichSettings />);

      expect(screen.getByTestId('immich-settings-form')).toBeInTheDocument();
      expect(screen.getByTestId('immich-server-url-input')).toBeInTheDocument();
      expect(screen.getByTestId('immich-api-key-input')).toBeInTheDocument();
      expect(screen.getByTestId('immich-connect-button')).toBeInTheDocument();
    });

    it('shows a validation error when the server URL is not a valid URL', async () => {
      render(<ImmichSettings />);

      fireEvent.change(screen.getByTestId('immich-server-url-input'), {
        target: { value: 'not-a-valid-url' },
      });
      fireEvent.change(screen.getByTestId('immich-api-key-input'), {
        target: { value: 'some-key' },
      });
      fireEvent.click(screen.getByTestId('immich-connect-button'));

      expect(
        await screen.findByText(/must be a valid url/i)
      ).toBeInTheDocument();
      expect(connectMutate).not.toHaveBeenCalled();
    });

    it('shows required-field errors when submitting empty', async () => {
      render(<ImmichSettings />);

      fireEvent.click(screen.getByTestId('immich-connect-button'));

      expect(
        await screen.findByText(/server url is required/i)
      ).toBeInTheDocument();
      expect(screen.getByText(/api key is required/i)).toBeInTheDocument();
      expect(connectMutate).not.toHaveBeenCalled();
    });

    it('submits trimmed values to the connect mutation', async () => {
      render(<ImmichSettings />);

      fireEvent.change(screen.getByTestId('immich-server-url-input'), {
        target: { value: 'https://immich.example.com' },
      });
      fireEvent.change(screen.getByTestId('immich-api-key-input'), {
        target: { value: '  secret-key  ' },
      });
      fireEvent.click(screen.getByTestId('immich-connect-button'));

      await waitFor(() => {
        expect(connectMutate).toHaveBeenCalledWith(
          { server_url: 'https://immich.example.com', api_key: 'secret-key' },
          expect.objectContaining({ onSuccess: expect.any(Function) })
        );
      });
    });
  });

  describe('connected state', () => {
    it('shows the connected panel with a disconnect button and no form', () => {
      render(<ImmichSettings connected />);

      expect(
        screen.getByText(/successfully connected to immich/i)
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('immich-disconnect-button')
      ).toBeInTheDocument();
      expect(
        screen.queryByTestId('immich-settings-form')
      ).not.toBeInTheDocument();
    });

    it('calls the disconnect mutation when the disconnect button is clicked', () => {
      render(<ImmichSettings connected />);

      fireEvent.click(screen.getByTestId('immich-disconnect-button'));
      expect(disconnectMutate).toHaveBeenCalledTimes(1);
    });
  });
});
