/**
 * Integrations management page.
 *
 * Provides interface for managing external integrations including
 * Google Contacts sync, status monitoring, and health checks.
 */

'use client';

import { AlertCircle } from 'lucide-react';
import { useIntegrations } from '@/lib/api/integrations';
import { Card, CardContent } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { LoadingSpinner } from '@/components/ui/loading';
import { IntegrationPanel } from '@/components/integrations/IntegrationPanel';
import { DeadLetterQueue } from '@/components/integrations/DeadLetterQueue';
import { ContactSuggestionsCard } from '@/components/integrations/ContactSuggestionsCard';

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

  if (integrationsLoading) {
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

          <ContactSuggestionsCard />

          <DeadLetterQueue />
        </div>
      </div>
    </div>
  );
}
