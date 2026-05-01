import { Cloud, Database } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { IntegrationData } from '@/types/integrations';
import { ConnectionControls } from './ConnectionControls';
import { SyncControls } from './SyncControls';

// Map integration ID to a specific icon
function getIntegrationIcon(id: string) {
  switch (id) {
    case 'google':
      return <Cloud className='h-5 w-5 text-blue-500' />;
    case 'strava':
      return <Database className='h-5 w-5 text-orange-500' />;
    default:
      return <Cloud className='h-5 w-5 text-gray-500' />;
  }
}

function getStatusBadge(status: string) {
  switch (status) {
    case 'connected':
      return <Badge variant='default'>Connected</Badge>;
    case 'disconnected':
      return <Badge variant='secondary'>Disconnected</Badge>;
    case 'error':
      return <Badge variant='destructive'>Error</Badge>;
    case 'token_expired':
      return <Badge variant='destructive'>Token Expired</Badge>;
    default:
      return <Badge variant='secondary'>{status}</Badge>;
  }
}

export interface IntegrationPanelProps {
  integration: IntegrationData;
}

export function IntegrationPanel({ integration }: IntegrationPanelProps) {
  const { id, attributes } = integration;
  const {
    name,
    status,
    capabilities,
    sync_summary,
    needs_reauth,
    needs_reconsent,
  } = attributes;

  const connected = status !== 'disconnected';

  return (
    <Card className='mb-6' data-testid={`integration-panel-${id}`}>
      <CardHeader>
        <CardTitle className='flex items-center justify-between'>
          <div className='flex flex-wrap items-center gap-2'>
            {getIntegrationIcon(id)}
            <span>{name}</span>
            {capabilities.map(cap => (
              <Badge
                key={cap}
                variant='outline'
                className='text-xs font-normal'
              >
                {cap}
              </Badge>
            ))}
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className='space-y-6'>
          {/* Status Display */}
          <div className='flex items-center justify-between'>
            <div className='space-y-1'>
              <div className='flex items-center gap-2'>
                {getStatusBadge(status)}
                <Badge variant='outline'>
                  {sync_summary.sync_count} items synced
                </Badge>
              </div>
              {sync_summary.last_sync_time && (
                <p className='text-muted-foreground text-sm'>
                  Last synced:{' '}
                  {new Date(sync_summary.last_sync_time).toLocaleString()}
                </p>
              )}
            </div>
          </div>

          <ConnectionControls
            integrationId={id}
            connected={connected}
            needsReauth={needs_reauth}
            needsReconsent={needs_reconsent}
          />

          <SyncControls
            integrationId={id}
            capabilities={capabilities}
            connected={connected}
            needsReauth={needs_reauth}
            needsReconsent={needs_reconsent}
          />
        </div>
      </CardContent>
    </Card>
  );
}
