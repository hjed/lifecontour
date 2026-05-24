/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConnectionControls } from '../ConnectionControls';
import {
  useOAuthAuthorize,
  useOAuthDisconnect,
  useReregisterWebhooks,
} from '@/lib/api/integrations';

jest.mock('@/lib/api/integrations', () => ({
  useOAuthAuthorize: jest.fn(),
  useOAuthDisconnect: jest.fn(),
  useReregisterWebhooks: jest.fn(),
}));

describe('ConnectionControls', () => {
  const mockAuthorize = jest.fn();
  const mockDisconnect = jest.fn();
  const mockReregister = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    (useOAuthAuthorize as jest.Mock).mockReturnValue({
      mutate: mockAuthorize,
      isPending: false,
    });
    (useOAuthDisconnect as jest.Mock).mockReturnValue({
      mutate: mockDisconnect,
      isPending: false,
    });
    (useReregisterWebhooks as jest.Mock).mockReturnValue({
      mutate: mockReregister,
      isPending: false,
    });
  });

  it('renders connect button when disconnected', async () => {
    const user = userEvent.setup();
    render(
      <ConnectionControls
        integrationId='google'
        connected={false}
        needsReauth={false}
        needsReconsent={false}
      />
    );

    const connectButton = screen.getByRole('button', { name: /connect/i });
    expect(connectButton).toBeInTheDocument();

    await user.click(connectButton);
    expect(mockAuthorize).toHaveBeenCalledWith({
      redirect_url: '/integrations',
    });
  });

  it('renders disconnect button when connected', async () => {
    const user = userEvent.setup();
    render(
      <ConnectionControls
        integrationId='google'
        connected={true}
        needsReauth={false}
        needsReconsent={false}
      />
    );

    const disconnectButton = screen.getByRole('button', {
      name: /disconnect/i,
    });
    expect(disconnectButton).toBeInTheDocument();

    await user.click(disconnectButton);
    expect(mockDisconnect).toHaveBeenCalled();
  });

  it('shows reauthorize and reregister webhooks buttons when connected (non-snipeit)', async () => {
    const user = userEvent.setup();
    render(
      <ConnectionControls
        integrationId='google'
        connected={true}
        needsReauth={false}
        needsReconsent={false}
      />
    );

    const reauthButton = screen.getByRole('button', { name: /reauthorize/i });
    const reregisterButton = screen.getByRole('button', {
      name: /reregister webhooks/i,
    });

    expect(reauthButton).toBeInTheDocument();
    expect(reregisterButton).toBeInTheDocument();

    await user.click(reauthButton);
    expect(mockAuthorize).toHaveBeenCalledWith({
      redirect_url: '/integrations',
    });

    await user.click(reregisterButton);
    expect(mockReregister).toHaveBeenCalled();
  });

  it('hides reauthorize and reregister webhooks buttons when connected (snipeit)', () => {
    render(
      <ConnectionControls
        integrationId='snipeit'
        connected={true}
        needsReauth={false}
        needsReconsent={false}
      />
    );

    expect(
      screen.queryByRole('button', { name: /reauthorize/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /reregister webhooks/i })
    ).not.toBeInTheDocument();
  });

  it('shows reauth banner and triggers reauthorize when needsReauth is true', async () => {
    const user = userEvent.setup();
    render(
      <ConnectionControls
        integrationId='google'
        connected={true}
        needsReauth={true}
        needsReconsent={false}
      />
    );

    expect(screen.getByText('Connection expired')).toBeInTheDocument();

    const relinkButton = screen.getByRole('button', {
      name: /relink account/i,
    });
    expect(relinkButton).toBeInTheDocument();

    const reregisterButton = screen.getByRole('button', {
      name: /reregister webhooks/i,
    });
    expect(reregisterButton).toBeDisabled();

    await user.click(relinkButton);
    expect(mockAuthorize).toHaveBeenCalledWith({
      redirect_url: '/integrations',
    });
  });

  it('shows reconsent banner and triggers reauthorize when needsReconsent is true', async () => {
    const user = userEvent.setup();
    render(
      <ConnectionControls
        integrationId='google'
        connected={true}
        needsReauth={false}
        needsReconsent={true}
      />
    );

    expect(screen.getByText('Permissions required')).toBeInTheDocument();

    const upgradeButton = screen.getByRole('button', {
      name: /upgrade permissions/i,
    });
    expect(upgradeButton).toBeInTheDocument();

    const reregisterButton = screen.getByRole('button', {
      name: /reregister webhooks/i,
    });
    expect(reregisterButton).toBeDisabled();

    await user.click(upgradeButton);
    expect(mockAuthorize).toHaveBeenCalledWith({
      redirect_url: '/integrations',
    });
  });

  it('disables buttons when loading', () => {
    (useOAuthAuthorize as jest.Mock).mockReturnValue({
      mutate: mockAuthorize,
      isPending: true,
    });
    (useOAuthDisconnect as jest.Mock).mockReturnValue({
      mutate: mockDisconnect,
      isPending: true,
    });
    (useReregisterWebhooks as jest.Mock).mockReturnValue({
      mutate: mockReregister,
      isPending: true,
    });

    render(
      <ConnectionControls
        integrationId='google'
        connected={true}
        needsReauth={false}
        needsReconsent={false}
      />
    );

    expect(screen.getByRole('button', { name: /disconnect/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /reauthorize/i })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: /reregister webhooks/i })
    ).toBeDisabled();
  });
});
