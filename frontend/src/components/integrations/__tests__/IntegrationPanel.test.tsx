/** @jest-environment jsdom */
import { render, screen } from '@testing-library/react';
import { IntegrationPanel } from '../IntegrationPanel';
import type { IntegrationData, IntegrationStatus } from '@/types/integrations';
import {
  useOAuthAuthorize,
  useOAuthDisconnect,
  useGenericSync,
  useReregisterWebhooks,
  useRotateSnipeItWebhookUrl,
  useSnipeItWebhookUrl,
} from '@/lib/api/integrations';

// Mock the API hooks used by the connection/sync/action controls. The panel's
// conditional-rendering logic does not depend on the hook results, only on the
// `integration` prop, so safe defaults are sufficient.
jest.mock('@/lib/api/integrations', () => ({
  useOAuthAuthorize: jest.fn(),
  useOAuthDisconnect: jest.fn(),
  useGenericSync: jest.fn(),
  useReregisterWebhooks: jest.fn(),
  useRotateSnipeItWebhookUrl: jest.fn(),
  useSnipeItWebhookUrl: jest.fn(),
}));

// Stub the heavier display children that are not under test here; each is
// covered by its own concerns. We render a marker for ImmichConflicts so we can
// assert the panel-level "immich only" branch.
jest.mock('../SyncHistory', () => ({ SyncHistory: () => null }));
jest.mock('../HealthStatus', () => ({ HealthStatus: () => null }));
jest.mock('../IntegrationSettings', () => ({
  IntegrationSettings: () => null,
}));
jest.mock('../ImmichConflicts', () => ({
  ImmichConflicts: () => <div data-testid='immich-conflicts-stub' />,
}));

const mutationResult = { mutate: jest.fn(), isPending: false };

beforeEach(() => {
  jest.clearAllMocks();
  (useOAuthAuthorize as jest.Mock).mockReturnValue(mutationResult);
  (useOAuthDisconnect as jest.Mock).mockReturnValue(mutationResult);
  (useGenericSync as jest.Mock).mockReturnValue(mutationResult);
  (useReregisterWebhooks as jest.Mock).mockReturnValue(mutationResult);
  (useRotateSnipeItWebhookUrl as jest.Mock).mockReturnValue(mutationResult);
  (useSnipeItWebhookUrl as jest.Mock).mockReturnValue({ data: undefined });
});

function makeIntegration(
  overrides: {
    id?: string;
    name?: string;
    status?: IntegrationStatus;
    capabilities?: string[];
    needs_reauth?: boolean;
    needs_reconsent?: boolean;
    sync_count?: number;
    last_sync_time?: string | null;
  } = {}
): IntegrationData {
  const {
    id = 'google',
    name = 'Google',
    status = 'connected',
    capabilities = ['contacts_sync', 'calendar_sync'],
    needs_reauth = false,
    needs_reconsent = false,
    sync_count = 0,
    last_sync_time = null,
  } = overrides;

  return {
    id,
    type: 'integration',
    attributes: {
      name,
      status,
      capabilities,
      needs_reauth,
      needs_reconsent,
      sync_summary: { last_sync_time, sync_count, error_count: 0 },
    },
  };
}

describe('IntegrationPanel', () => {
  describe('disconnected state', () => {
    it('shows the Connect button and hides disconnect/sync/action controls', () => {
      render(
        <IntegrationPanel
          integration={makeIntegration({ status: 'disconnected' })}
        />
      );

      expect(screen.getByText('Disconnected')).toBeInTheDocument();
      expect(screen.getByTestId('connect-google')).toBeInTheDocument();
      expect(screen.queryByTestId('disconnect-google')).not.toBeInTheDocument();
      // Sync controls and maintenance actions only render when connected
      expect(
        screen.queryByTestId('trigger-google-contacts-sync')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('reregister-webhooks-google')
      ).not.toBeInTheDocument();
      expect(screen.queryByTestId('reauth-google')).not.toBeInTheDocument();
    });
  });

  describe('connected state', () => {
    it('shows disconnect, per-capability sync, and maintenance controls', () => {
      render(<IntegrationPanel integration={makeIntegration()} />);

      expect(screen.getByText('Connected')).toBeInTheDocument();
      expect(screen.getByTestId('disconnect-google')).toBeInTheDocument();
      expect(screen.queryByTestId('connect-google')).not.toBeInTheDocument();

      // One sync button per capability, testid derived from capability
      expect(
        screen.getByTestId('trigger-google-contacts-sync')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('trigger-google-calendar-sync')
      ).toBeInTheDocument();

      // Maintenance actions
      expect(
        screen.getByTestId('reregister-webhooks-google')
      ).toBeInTheDocument();
      expect(screen.getByTestId('reauth-google')).toBeInTheDocument();
    });

    it('renders a capability badge and the synced-items count', () => {
      render(
        <IntegrationPanel integration={makeIntegration({ sync_count: 12 })} />
      );

      expect(screen.getByText('Contacts')).toBeInTheDocument();
      expect(screen.getByText('Calendar')).toBeInTheDocument();
      expect(screen.getByText('12 items synced')).toBeInTheDocument();
    });

    it('does not show the scope-upgrade banner when reconsent is not needed', () => {
      render(<IntegrationPanel integration={makeIntegration()} />);
      expect(
        screen.queryByTestId('scope-upgrade-banner-google')
      ).not.toBeInTheDocument();
    });
  });

  describe('attention states', () => {
    it('shows the scope-upgrade banner and disables sync when reconsent is needed', () => {
      render(
        <IntegrationPanel
          integration={makeIntegration({ needs_reconsent: true })}
        />
      );

      expect(
        screen.getByTestId('scope-upgrade-banner-google')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('upgrade-permissions-button-google')
      ).toBeInTheDocument();
      // Sync buttons still render but are disabled
      expect(screen.getByTestId('trigger-google-contacts-sync')).toBeDisabled();
    });

    it('shows the token-expired banner when reauth is needed', () => {
      render(
        <IntegrationPanel
          integration={makeIntegration({ needs_reauth: true })}
        />
      );

      expect(
        screen.getByTestId('token-expired-banner-google')
      ).toBeInTheDocument();
      expect(screen.getByTestId('relink-button-google')).toBeInTheDocument();
    });

    it('treats token_expired status as connected and shows its badge', () => {
      render(
        <IntegrationPanel
          integration={makeIntegration({ status: 'token_expired' })}
        />
      );

      expect(screen.getByText('Token Expired')).toBeInTheDocument();
      // token_expired is still "connected" for control purposes
      expect(screen.getByTestId('disconnect-google')).toBeInTheDocument();
    });

    it('renders the error status badge', () => {
      render(
        <IntegrationPanel integration={makeIntegration({ status: 'error' })} />
      );
      expect(screen.getByText('Error')).toBeInTheDocument();
    });
  });

  describe('provider-specific rendering', () => {
    it('hides OAuth connect/disconnect and uses the webhook-URL action for snipeit', () => {
      render(
        <IntegrationPanel
          integration={makeIntegration({
            id: 'snipeit',
            name: 'Snipe-IT',
            capabilities: ['gear_usage'],
          })}
        />
      );

      // snipeit authenticates via API key, so ConnectionControls is not rendered
      expect(screen.queryByTestId('connect-snipeit')).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('disconnect-snipeit')
      ).not.toBeInTheDocument();

      // Webhook URL action instead of re-register webhooks
      expect(screen.getByTestId('get-webhook-url-snipeit')).toBeInTheDocument();
      expect(
        screen.queryByTestId('reregister-webhooks-snipeit')
      ).not.toBeInTheDocument();
      expect(screen.getByTestId('reauth-snipeit')).toBeInTheDocument();
    });

    it('renders the Immich conflicts section only for immich', () => {
      const { rerender } = render(
        <IntegrationPanel integration={makeIntegration()} />
      );
      expect(
        screen.queryByTestId('immich-conflicts-stub')
      ).not.toBeInTheDocument();

      rerender(
        <IntegrationPanel
          integration={makeIntegration({
            id: 'immich',
            name: 'Immich',
            capabilities: ['contacts_sync', 'album_sync'],
          })}
        />
      );
      expect(screen.getByTestId('immich-conflicts-stub')).toBeInTheDocument();
      expect(
        screen.getByTestId('trigger-immich-contacts-sync')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('trigger-immich-album-sync')
      ).toBeInTheDocument();
    });
  });
});
