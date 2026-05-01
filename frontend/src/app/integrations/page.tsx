/**
 * Integrations management page.
 *
 * Provides interface for managing external integrations including
 * Google Contacts sync, status monitoring, and health checks.
 */

'use client';

import { Settings, Activity, Clock, AlertCircle } from 'lucide-react';
import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import {
  useIntegrations,
  useIntegrationHealth,
  useSyncHistory,
} from '@/lib/api/integrations';
import {
  SyncJobListResponse,
  IntegrationHealthAttributes,
} from '@/types/integrations';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { LoadingSpinner } from '@/components/ui/loading';
import { IntegrationPanel } from '@/components/integrations/IntegrationPanel';
import { DeadLetterQueue } from '@/components/integrations/DeadLetterQueue';

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

  let content: React.ReactNode;

  if (historyLoading) {
    content = (
      <div className='space-y-2'>
        {[1, 2, 3].map(val => (
          <Skeleton key={`skeleton-${val}`} className='h-16 w-full' />
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
    data: integrationsData,
    isLoading: integrationsLoading,
    error: integrationsError,
  } = useIntegrations();

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

  if (integrationsLoading || healthLoading || historyLoading) {
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

  const integrations = integrationsData?.data || [];

  return (
    <div className='container mx-auto py-8'>
      <div className='mb-8'>
        <h1 className='text-3xl font-bold tracking-tight'>Integrations</h1>
        <p className='text-muted-foreground'>
          Manage your external integrations and sync settings
        </p>
      </div>

      <div className='grid gap-6 lg:grid-cols-3'>
        {/* Dynamic Integration Panels */}
        <div className='space-y-6 lg:col-span-2'>
          {integrationsError ? (
            <Alert variant='destructive'>
              <AlertCircle className='h-4 w-4' />
              <AlertTitle>Error loading integrations</AlertTitle>
              <AlertDescription>{integrationsError.message}</AlertDescription>
            </Alert>
          ) : integrations.length === 0 ? (
            <Card>
              <CardContent className='pt-6'>
                <p className='text-muted-foreground text-center'>
                  No integrations available.
                </p>
              </CardContent>
            </Card>
          ) : (
            integrations.map(integration => (
              <IntegrationPanel
                key={integration.id}
                integration={integration}
              />
            ))
          )}

          {/* Sync History */}
          <SyncHistorySection
            historyData={historyData}
            historyLoading={historyLoading}
            historyError={historyError}
          />
        </div>

        {/* Sidebar: System Health & Settings */}
        <div>
          <HealthSection
            healthData={healthData}
            healthLoading={healthLoading}
            healthError={healthError}
          />

          <DeadLetterQueue />

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
