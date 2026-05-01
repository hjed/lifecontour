'use client';

import {
  KeyRound,
  RefreshCw,
  Settings,
  ShieldAlert,
  Users,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { useOAuthAuthorize, useOAuthDisconnect } from '@/lib/api/integrations';

interface ConnectionControlsProps {
  integrationId: string;
  connected: boolean;
  needsReauth?: boolean;
  needsReconsent?: boolean;
}

export function ConnectionControls({
  integrationId,
  connected,
  needsReauth,
  needsReconsent,
}: ConnectionControlsProps) {
  const { mutate: authorizeOAuth, isPending: oauthLoading } =
    useOAuthAuthorize(integrationId);
  const { mutate: disconnectOAuth, isPending: disconnectLoading } =
    useOAuthDisconnect(integrationId);

  const handleConnect = () => {
    authorizeOAuth({ redirect_url: '/integrations' });
  };

  const handleDisconnect = () => {
    disconnectOAuth();
  };

  return (
    <div className='flex flex-col gap-4'>
      {/* Scope Upgrade Banner */}
      {connected && needsReconsent && (
        <Alert variant='destructive' data-testid='scope-upgrade-banner'>
          <ShieldAlert className='h-4 w-4' />
          <AlertTitle>Permissions required</AlertTitle>
          <AlertDescription className='flex flex-col gap-2'>
            <p>
              Your account is connected but does not have the required
              permissions. Upgrade your permissions to enable full
              synchronisation.
            </p>
            <div>
              <Button
                size='sm'
                onClick={handleConnect}
                disabled={oauthLoading}
                data-testid='upgrade-permissions-button'
              >
                {oauthLoading ? (
                  <RefreshCw className='mr-2 h-4 w-4 animate-spin' />
                ) : (
                  <ShieldAlert className='mr-2 h-4 w-4' />
                )}
                Upgrade Permissions
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {/* Token Expired Banner */}
      {connected && needsReauth && (
        <Alert variant='destructive' data-testid='token-expired-banner'>
          <KeyRound className='h-4 w-4' />
          <AlertTitle>Connection expired</AlertTitle>
          <AlertDescription className='flex flex-col gap-2'>
            <p>
              Your account connection has expired or been revoked. Please relink
              your account to resume synchronisation.
            </p>
            <div>
              <Button
                size='sm'
                onClick={handleConnect}
                disabled={oauthLoading}
                data-testid='relink-button'
              >
                {oauthLoading ? (
                  <RefreshCw className='mr-2 h-4 w-4 animate-spin' />
                ) : (
                  <KeyRound className='mr-2 h-4 w-4' />
                )}
                Relink Account
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      <div className='flex gap-2'>
        {connected ? (
          <Button
            variant='outline'
            onClick={handleDisconnect}
            disabled={disconnectLoading}
            data-testid={`disconnect-${integrationId}`}
          >
            {disconnectLoading ? (
              <RefreshCw className='mr-2 h-4 w-4 animate-spin' />
            ) : (
              <Settings className='mr-2 h-4 w-4' />
            )}
            Disconnect
          </Button>
        ) : (
          <Button
            onClick={handleConnect}
            disabled={oauthLoading}
            data-testid={`connect-${integrationId}`}
          >
            {oauthLoading ? (
              <RefreshCw className='mr-2 h-4 w-4 animate-spin' />
            ) : (
              <Users className='mr-2 h-4 w-4' />
            )}
            Connect Account
          </Button>
        )}
      </div>
    </div>
  );
}
