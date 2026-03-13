/**
 * Integrations management page.
 *
 * Provides interface for managing external integrations including
 * Google Contacts sync, status monitoring, and health checks.
 */

'use client';

import {
  RefreshCw,
  Settings,
  Activity,
  Clock,
  Users,
  AlertCircle,
} from 'lucide-react';
import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import {
  useGoogleStatus,
  useGoogleSync,
  useIntegrationHealth,
  useSyncHistory,
  useGoogleOAuthAuthorize,
  useGoogleOAuthDisconnect,
} from '@/lib/api/integrations';
import {
  SyncType,
  SyncJobListResponse,
  IntegrationHealthAttributes,
} from '@/types/integrations';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { LoadingSpinner } from '@/components/ui/loading';

// Generic helper function for safe date/time formatting
function formatDateGenericSafely(
  dateString: string | null,
  formatString: string,
  fallback: string
): string {
  if (!dateString) return 'Never';

  try {
    return format(new Date(dateString), formatString, {
      locale: enAU,
    });
  } catch {
    return fallback;
  }
}

// Helper function for safe date formatting
function formatDateSafely(dateString: string | null): string {
  return formatDateGenericSafely(dateString, 'PPp', 'Invalid date');
}

// Helper function for safe time formatting
function formatTimeSafely(dateString: string | null): string {
  return formatDateGenericSafely(dateString, 'p', 'Invalid time');
}

// Helper function to get badge variant for sync status
function getSyncStatusVariant(
  status: string
): 'default' | 'destructive' | 'secondary' {
  if (status === 'completed') return 'default';
  if (status === 'failed') return 'destructive';
  return 'secondary';
}

// Sync Controls Component
interface SyncControlsProps {
  readonly connected: boolean;
  readonly syncLoading: boolean;
  readonly oauthLoading: boolean;
  readonly disconnectLoading: boolean;
  readonly onSync: (syncType: SyncType) => void;
  readonly onConnect: () => void;
  readonly onDisconnect: () => void;
  readonly syncError: Error | null;
}

function SyncControls({
  connected,
  syncLoading,
  oauthLoading,
  disconnectLoading,
  onSync,
  onConnect,
  onDisconnect,
  syncError,
}: SyncControlsProps) {
  return (
    <>
      <div className='flex gap-2'>
        {connected ? (
          <>
            <Button
              onClick={() => onSync('smart')}
              disabled={syncLoading}
              data-testid='trigger-google-sync'
            >
              {syncLoading ? (
                <RefreshCw className='mr-2 h-4 w-4 animate-spin' />
              ) : (
                <RefreshCw className='mr-2 h-4 w-4' />
              )}
              Smart Sync
            </Button>
            <Button
              variant='outline'
              onClick={() => onSync('full')}
              disabled={syncLoading}
            >
              Full Sync
            </Button>
            <Button
              variant='outline'
              onClick={onDisconnect}
              disabled={disconnectLoading}
              data-testid='disconnect-google'
            >
              {disconnectLoading ? (
                <RefreshCw className='mr-2 h-4 w-4 animate-spin' />
              ) : (
                <Settings className='mr-2 h-4 w-4' />
              )}
              Disconnect
            </Button>
          </>
        ) : (
          <Button
            onClick={onConnect}
            disabled={oauthLoading}
            data-testid='connect-google'
          >
            {oauthLoading ? (
              <RefreshCw className='mr-2 h-4 w-4 animate-spin' />
            ) : (
              <Users className='mr-2 h-4 w-4' />
            )}
            Connect Google Account
          </Button>
        )}
      </div>

      {syncLoading && (
        <div data-testid='sync-progress'>
          <LoadingSpinner size='sm' text='Sync in progress...' />
        </div>
      )}

      {syncError && (
        <Alert>
          <AlertCircle className='h-4 w-4' />
          <AlertDescription>{syncError.message}</AlertDescription>
        </Alert>
      )}
    </>
  );
}

// Sync History Section Component
interface SyncHistorySectionProps {
  readonly historyData: SyncJobListResponse | undefined;
  readonly historyLoading: boolean;
  readonly historyError: Error | null;
}

function SyncHistorySection({
  historyData,
  historyLoading,
  historyError,
}: SyncHistorySectionProps) {
  const recentJobs = historyData?.data || [];

  // Determine content to render
  let content: React.ReactNode;

  if (historyLoading) {
    content = (
      <div className='space-y-2'>
        {new Array(3).fill(null).map((_, i) => (
          <Skeleton key={`skeleton-${i}`} className='h-16 w-full' />
        ))}
      </div>
    );
  } else if (historyError) {
    content = (
      <Alert>
        <AlertCircle className='h-4 w-4' />
        <AlertDescription>
          Failed to load sync history: {historyError.message}
        </AlertDescription>
      </Alert>
    );
  } else if (recentJobs.length > 0) {
    content = (
      <div className='space-y-3'>
        {recentJobs.map(job => (
          <div
            key={job.id}
            className='flex items-center justify-between rounded-lg border p-3'
            data-testid='sync-job-item'
          >
            <div className='space-y-1'>
              <div className='flex items-center gap-2'>
                <Badge variant={getSyncStatusVariant(job.attributes.status)}>
                  {job.attributes.status}
                </Badge>
                <span className='text-sm font-medium'>
                  {job.attributes.syncType} sync
                </span>
              </div>
              <p className='text-muted-foreground text-sm'>
                {formatDateSafely(job.attributes.createdAt)}
              </p>
            </div>
            {job.attributes.contactsProcessed != null && (
              <div className='text-right text-sm'>
                <p>{job.attributes.contactsProcessed} processed</p>
                {job.attributes.contactsCreated != null && (
                  <p className='text-muted-foreground'>
                    {job.attributes.contactsCreated} created
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  } else {
    content = (
      <p className='text-muted-foreground py-4 text-center'>
        No sync jobs found
      </p>
    );
  }

  return (
    <Card className='mt-6' data-testid='sync-history'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <Clock className='h-5 w-5 text-green-500' />
          Recent Sync Jobs
        </CardTitle>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  );
}

// Health Section Component
interface HealthSectionProps {
  readonly healthData:
    | { data: { attributes: IntegrationHealthAttributes } }
    | undefined;
  readonly healthLoading: boolean;
  readonly healthError: Error | null;
}

function HealthSection({
  healthData,
  healthLoading,
  healthError,
}: HealthSectionProps) {
  const health = healthData?.data?.attributes;

  // Determine content to render
  let content: React.ReactNode;

  if (healthLoading) {
    content = (
      <div className='space-y-2'>
        <Skeleton className='h-4 w-full' />
        <Skeleton className='h-4 w-3/4' />
        <Skeleton className='h-4 w-1/2' />
      </div>
    );
  } else if (healthError) {
    content = (
      <Alert>
        <AlertCircle className='h-4 w-4' />
        <AlertDescription>
          Failed to load health status: {healthError.message}
        </AlertDescription>
      </Alert>
    );
  } else if (health) {
    content = (
      <div className='space-y-3'>
        <div className='flex items-center justify-between'>
          <span className='text-sm'>Overall</span>
          <Badge
            variant={health.overall === 'healthy' ? 'default' : 'destructive'}
          >
            {health.overall}
          </Badge>
        </div>
        <div className='flex items-center justify-between'>
          <span className='text-sm'>Redis: {health.redis.status}</span>
          <Badge
            variant={
              health.redis.status === 'healthy' ? 'default' : 'destructive'
            }
          >
            {health.redis.latency}ms
          </Badge>
        </div>
        <div className='flex items-center justify-between'>
          <span className='text-sm'>Worker: {health.worker.status}</span>
          {health.worker.lastSeen && (
            <span className='text-muted-foreground text-xs'>
              {formatTimeSafely(health.worker.lastSeen)}
            </span>
          )}
        </div>
        <p className='text-muted-foreground text-xs'>
          Last checked: {formatTimeSafely(health.lastChecked)}
        </p>
      </div>
    );
  } else {
    content = null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <Activity className='h-5 w-5 text-green-500' />
          System Health
        </CardTitle>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  );
}

export default function IntegrationsPage() {
  return (
    <AuthGuard>
      <IntegrationsPageContent />
    </AuthGuard>
  );
}

function IntegrationsPageContent() {
  const {
    data: statusData,
    isLoading: statusLoading,
    error: statusError,
  } = useGoogleStatus();

  const {
    data: healthData,
    isLoading: healthLoading,
    error: healthError,
  } = useIntegrationHealth();

  const {
    data: historyData,
    isLoading: historyLoading,
    error: historyError,
  } = useSyncHistory({ limit: 5 });

  const {
    mutate: triggerSync,
    isPending: syncLoading,
    error: syncError,
  } = useGoogleSync();

  const { mutate: authorizeOAuth, isPending: oauthLoading } =
    useGoogleOAuthAuthorize();

  const { mutate: disconnectOAuth, isPending: disconnectLoading } =
    useGoogleOAuthDisconnect();

  const status = statusData?.data?.attributes;

  const handleSync = (syncType: SyncType) => {
    triggerSync(syncType);
  };

  const handleConnectGoogle = () => {
    // OAuth flow type is now encoded in the state parameter by the backend
    authorizeOAuth({ redirect_url: '/integrations' });
  };

  const handleDisconnectGoogle = () => {
    disconnectOAuth();
  };

  if (statusLoading || healthLoading || historyLoading) {
    return (
      <div className='container mx-auto py-8'>
        <div className='mb-8'>
          <h1 className='text-3xl font-bold tracking-tight'>Integrations</h1>
          <p className='text-muted-foreground'>
            Manage your external integrations and sync settings
          </p>
        </div>
        <LoadingSpinner
          size='lg'
          text='Loading integrations...'
          data-testid='loading-spinner'
        />
      </div>
    );
  }

  return (
    <div className='container mx-auto py-8'>
      <div className='mb-8'>
        <h1 className='text-3xl font-bold tracking-tight'>Integrations</h1>
        <p className='text-muted-foreground'>
          Manage your external integrations and sync settings
        </p>
      </div>

      <div className='grid gap-6 lg:grid-cols-3'>
        {/* Google Contacts Integration */}
        <div className='lg:col-span-2'>
          <Card data-testid='google-integration'>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <Users className='h-5 w-5 text-blue-500' />
                Google Contacts
              </CardTitle>
            </CardHeader>
            <CardContent className='space-y-4'>
              {statusError && (
                <Alert>
                  <AlertCircle className='h-4 w-4' />
                  <AlertDescription>{statusError.message}</AlertDescription>
                </Alert>
              )}

              {status && (
                <>
                  {/* Status Display */}
                  <div className='flex items-center justify-between'>
                    <div className='space-y-1'>
                      <div className='flex items-center gap-2'>
                        <Badge
                          variant={status.connected ? 'default' : 'secondary'}
                          data-testid='integration-status'
                        >
                          {status.connected ? 'Connected' : 'Disconnected'}
                        </Badge>
                        <Badge variant='outline'>
                          {status.syncCount} contacts synced
                        </Badge>
                      </div>
                      {status.lastSync && (
                        <p className='text-muted-foreground text-sm'>
                          Last sync: {formatDateSafely(status.lastSync)}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Sync Controls */}
                  <SyncControls
                    connected={status.connected}
                    syncLoading={syncLoading}
                    oauthLoading={oauthLoading}
                    disconnectLoading={disconnectLoading}
                    onSync={handleSync}
                    onConnect={handleConnectGoogle}
                    onDisconnect={handleDisconnectGoogle}
                    syncError={syncError}
                  />
                </>
              )}
            </CardContent>
          </Card>

          {/* Sync History */}
          <SyncHistorySection
            historyData={historyData}
            historyLoading={historyLoading}
            historyError={historyError}
          />
        </div>

        {/* System Health */}
        <div>
          <HealthSection
            healthData={healthData}
            healthLoading={healthLoading}
            healthError={healthError}
          />

          {/* Settings */}
          <Card className='mt-6'>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <Settings className='h-5 w-5 text-gray-500' />
                Settings
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className='text-muted-foreground text-sm'>
                Integration settings will be available in a future update.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
