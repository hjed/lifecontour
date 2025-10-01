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
  useGoogleContactsStatus,
  useGoogleContactsSync,
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

// Helper function for safe date formatting
function formatDateSafely(dateString: string | null): string {
  if (!dateString) return 'Never';

  try {
    return format(new Date(dateString), 'PPp', {
      locale: enAU,
    });
  } catch {
    return 'Invalid date';
  }
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

  const {
    mutate: triggerSync,
    isPending: syncLoading,
    error: syncError,
  } = useGoogleContactsSync();

  const status = statusData?.data?.attributes;
  const health = healthData?.data?.attributes;
  const recentJobs = historyData?.data || [];

  const handleSync = (syncType: SyncType) => {
    triggerSync(syncType);
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
                      <Button>Connect Google Account</Button>
                    )}
                  </div>

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
                <div className='space-y-2'>
                  {[...Array(3)].map((_, i) => (
                    <Skeleton key={i} className='h-16 w-full' />
                  ))}
                </div>
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
                            variant={
                              job.attributes.status === 'completed'
                                ? 'default'
                                : job.attributes.status === 'failed'
                                  ? 'destructive'
                                  : 'secondary'
                            }
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
                <div className='space-y-2'>
                  <Skeleton className='h-4 w-full' />
                  <Skeleton className='h-4 w-3/4' />
                  <Skeleton className='h-4 w-1/2' />
                </div>
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
                    <Badge
                      variant={
                        health.overall === 'healthy' ? 'default' : 'destructive'
                      }
                    >
                      {health.overall}
                    </Badge>
                  </div>
                  <div className='flex items-center justify-between'>
                    <span className='text-sm'>
                      Redis: {health.redis.status}
                    </span>
                    <Badge
                      variant={
                        health.redis.status === 'healthy'
                          ? 'default'
                          : 'destructive'
                      }
                    >
                      {health.redis.latency}ms
                    </Badge>
                  </div>
                  <div className='flex items-center justify-between'>
                    <span className='text-sm'>
                      Worker: {health.worker.status}
                    </span>
                    {health.worker.lastSeen && (
                      <span className='text-muted-foreground text-xs'>
                        {format(new Date(health.worker.lastSeen), 'p', {
                          locale: enAU,
                        })}
                      </span>
                    )}
                  </div>
                  <p className='text-muted-foreground text-xs'>
                    Last checked:{' '}
                    {format(new Date(health.lastChecked), 'p', {
                      locale: enAU,
                    })}
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
