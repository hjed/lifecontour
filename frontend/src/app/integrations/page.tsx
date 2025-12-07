/**
 * Integrations management page.
 *
 * Provides interface for managing external integrations including
 * Google Contacts sync, status monitoring, and health checks.
 */

'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  RefreshCw,
  Settings,
  Activity,
  Clock,
  Users,
  AlertCircle,
  CheckCircle,
  Unlink,
} from 'lucide-react';
import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import { toast } from 'sonner';
import {
  useGoogleAccounts,
  useGoogleContactsStatus,
  useGoogleContactsSync,
  useInitiateGoogleOAuth,
  useDisconnectGoogleAccount,
  useIntegrationHealth,
  useSyncHistory,
} from '@/lib/api/integrations';
import { SyncType } from '@/types/integrations';
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

// Predefined error messages for security (prevents XSS via URL params)
const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  oauth_cancelled: 'Google OAuth was cancelled or failed',
  invalid_callback: 'Invalid OAuth callback',
  connection_failed: 'Failed to connect Google account',
  unknown: 'An unexpected error occurred',
} as const;

// Helper function for safe date formatting
function formatDateSafely(dateString: string | null): string {
  return formatDateGenericSafely(dateString, 'PPp', 'Invalid date');
}

// Helper function for safe time formatting
function formatTimeSafely(dateString: string | null): string {
  return formatDateGenericSafely(dateString, 'p', 'Invalid time');
}

// Badge variant helpers to avoid nested ternaries
type BadgeVariant = 'default' | 'secondary' | 'destructive' | 'outline';

function getSyncJobBadgeVariant(status: string): BadgeVariant {
  if (status === 'completed') return 'default';
  if (status === 'failed') return 'destructive';
  return 'secondary';
}

function getHealthBadgeVariant(status: string): BadgeVariant {
  return status === 'healthy' ? 'default' : 'destructive';
}

// Sub-component: Sync History Loading Skeleton
function SyncHistorySkeleton() {
  return (
    <div className='space-y-2'>
      {[1, 2, 3].map(i => (
        <Skeleton key={`history-skeleton-${i}`} className='h-16 w-full' />
      ))}
    </div>
  );
}

// Sub-component: Health Loading Skeleton
function HealthSkeleton() {
  return (
    <div className='space-y-2'>
      <Skeleton className='h-4 w-full' />
      <Skeleton className='h-4 w-3/4' />
      <Skeleton className='h-4 w-1/2' />
    </div>
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
  const router = useRouter();
  const searchParams = useSearchParams();

  const {
    data: statusData,
    isLoading: statusLoading,
    error: statusError,
  } = useGoogleContactsStatus();

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

  const { data: accountsData, isLoading: accountsLoading } =
    useGoogleAccounts();

  const {
    mutate: triggerSync,
    isPending: syncLoading,
    error: syncError,
  } = useGoogleContactsSync();

  const { mutate: initiateOAuth, isPending: oauthLoading } =
    useInitiateGoogleOAuth();

  const { mutate: disconnectAccount, isPending: disconnectLoading } =
    useDisconnectGoogleAccount();

  const status = statusData?.data?.attributes;
  const health = healthData?.data?.attributes;
  const recentJobs = historyData?.data || [];
  const googleAccounts = accountsData?.accounts || [];

  // Show success toast when connected
  useEffect(() => {
    if (searchParams.get('connected') === 'true') {
      toast.success('Google account connected successfully!');
      // Clear the query parameter using Next.js router (maintains routing state)
      router.replace('/integrations');
    }
    const errorParam = searchParams.get('error');
    if (errorParam) {
      // Use predefined message or fallback to generic error (XSS safe)
      const safeMessage =
        OAUTH_ERROR_MESSAGES[errorParam] || OAUTH_ERROR_MESSAGES.unknown;
      toast.error(safeMessage);
      // Clear the query parameter using Next.js router (maintains routing state)
      router.replace('/integrations');
    }
  }, [searchParams, router]);

  const handleSync = (syncType: SyncType) => {
    triggerSync(syncType);
  };

  const handleConnectGoogle = () => {
    initiateOAuth({ redirect_url: '/integrations' });
  };

  const handleDisconnectAccount = (email: string) => {
    // TODO: Replace native confirm() with a custom accessible dialog component
    // for better screen reader and keyboard support. See:
    // https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/
    if (confirm(`Are you sure you want to disconnect ${email}?`)) {
      disconnectAccount(email);
    }
  };

  if (statusLoading || healthLoading || historyLoading || accountsLoading) {
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
          <Card data-testid='google-contacts-integration'>
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
                  <div className='flex gap-2'>
                    {status.connected ? (
                      <>
                        <Button
                          onClick={() => handleSync('smart')}
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
                          onClick={() => handleSync('full')}
                          disabled={syncLoading}
                        >
                          Full Sync
                        </Button>
                      </>
                    ) : (
                      <Button
                        onClick={handleConnectGoogle}
                        disabled={oauthLoading}
                        data-testid='connect-google-btn'
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

                  {/* Connected Accounts */}
                  {googleAccounts.length > 0 && (
                    <div className='space-y-2'>
                      <h4 className='text-sm font-medium'>
                        Connected Accounts
                      </h4>
                      {googleAccounts.map(account => (
                        <div
                          key={account.id}
                          className='flex items-center justify-between rounded-lg border p-3'
                        >
                          <div className='flex items-center gap-2'>
                            <CheckCircle className='h-4 w-4 text-green-500' />
                            <span className='text-sm'>{account.email}</span>
                            {account.is_token_expired && (
                              <Badge variant='destructive'>Token Expired</Badge>
                            )}
                          </div>
                          <Button
                            variant='ghost'
                            size='sm'
                            onClick={() =>
                              handleDisconnectAccount(account.email)
                            }
                            disabled={disconnectLoading}
                          >
                            <Unlink className='h-4 w-4' />
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Sync Progress */}
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
              )}
            </CardContent>
          </Card>

          {/* Sync History */}
          <Card className='mt-6' data-testid='sync-history'>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <Clock className='h-5 w-5 text-green-500' />
                Recent Sync Jobs
              </CardTitle>
            </CardHeader>
            <CardContent>
              {historyLoading ? (
                <SyncHistorySkeleton />
              ) : historyError ? (
                <Alert>
                  <AlertCircle className='h-4 w-4' />
                  <AlertDescription>
                    Failed to load sync history: {historyError.message}
                  </AlertDescription>
                </Alert>
              ) : recentJobs.length > 0 ? (
                <div className='space-y-3'>
                  {recentJobs.map(job => (
                    <div
                      key={job.id}
                      className='flex items-center justify-between rounded-lg border p-3'
                      data-testid='sync-job-item'
                    >
                      <div className='space-y-1'>
                        <div className='flex items-center gap-2'>
                          <Badge
                            variant={getSyncJobBadgeVariant(
                              job.attributes.status
                            )}
                          >
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
                      {job.attributes.contactsProcessed && (
                        <div className='text-right text-sm'>
                          <p>{job.attributes.contactsProcessed} processed</p>
                          {job.attributes.contactsCreated && (
                            <p className='text-muted-foreground'>
                              {job.attributes.contactsCreated} created
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className='text-muted-foreground py-4 text-center'>
                  No sync jobs found
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* System Health */}
        <div>
          <Card>
            <CardHeader>
              <CardTitle className='flex items-center gap-2'>
                <Activity className='h-5 w-5 text-green-500' />
                System Health
              </CardTitle>
            </CardHeader>
            <CardContent>
              {healthLoading ? (
                <HealthSkeleton />
              ) : healthError ? (
                <Alert>
                  <AlertCircle className='h-4 w-4' />
                  <AlertDescription>
                    Failed to load health status: {healthError.message}
                  </AlertDescription>
                </Alert>
              ) : health ? (
                <div className='space-y-3'>
                  <div className='flex items-center justify-between'>
                    <span className='text-sm'>Overall</span>
                    <Badge variant={getHealthBadgeVariant(health.overall)}>
                      {health.overall}
                    </Badge>
                  </div>
                  <div className='flex items-center justify-between'>
                    <span className='text-sm'>
                      Redis: {health.redis.status}
                    </span>
                    <Badge variant={getHealthBadgeVariant(health.redis.status)}>
                      {health.redis.latency}ms
                    </Badge>
                  </div>
                  <div className='flex items-center justify-between'>
                    <span className='text-sm'>
                      Worker: {health.worker.status}
                    </span>
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
              ) : null}
            </CardContent>
          </Card>

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
