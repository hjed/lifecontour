'use client';

import { useState } from 'react';
import { Copy, KeyRound, Link2, RefreshCw, Webhook } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  useOAuthAuthorize,
  useReregisterWebhooks,
  useSnipeItWebhookUrl,
} from '@/lib/api/integrations';

interface IntegrationActionsProps {
  readonly integrationId: string;
  readonly connected: boolean;
}

/**
 * Action buttons for integration maintenance:
 * - Re-register Webhooks (Google, Strava)
 * - Get Webhook URL (Snipe-IT — manual webhook model)
 * - Re-authenticate (all OAuth integrations)
 */
export function IntegrationActions({
  integrationId,
  connected,
}: IntegrationActionsProps) {
  const [webhookUrlDialogOpen, setWebhookUrlDialogOpen] = useState(false);

  const { mutate: reregisterWebhooks, isPending: reregisterPending } =
    useReregisterWebhooks(integrationId);

  const { mutate: authorizeOAuth, isPending: oauthPending } =
    useOAuthAuthorize(integrationId);

  // Only fetch snipeit webhook URL when dialog is open
  const { data: webhookUrlData } = useSnipeItWebhookUrl(
    integrationId === 'snipeit' && webhookUrlDialogOpen
  );

  if (!connected) return null;

  const handleReregisterWebhooks = () => {
    reregisterWebhooks();
  };

  const handleReauth = () => {
    authorizeOAuth({ redirect_url: '/integrations' });
  };

  const handleCopyWebhookUrl = async () => {
    const url = webhookUrlData?.data?.attributes?.webhook_url;
    if (url) {
      await navigator.clipboard.writeText(url);
      toast.success('Webhook URL copied to clipboard');
    }
  };

  const isSnipeIt = integrationId === 'snipeit';

  return (
    <>
      <TooltipProvider>
        <div className='flex flex-wrap items-center gap-2'>
          {/* Webhook action */}
          {isSnipeIt ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant='outline'
                  size='sm'
                  className='gap-2'
                  onClick={() => setWebhookUrlDialogOpen(true)}
                  data-testid={`get-webhook-url-${integrationId}`}
                >
                  <Link2 className='h-4 w-4' />
                  Webhook URL
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                Get the webhook URL to configure in Snipe-IT
              </TooltipContent>
            </Tooltip>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant='outline'
                  size='sm'
                  className='gap-2'
                  onClick={handleReregisterWebhooks}
                  disabled={reregisterPending}
                  data-testid={`reregister-webhooks-${integrationId}`}
                >
                  {reregisterPending ? (
                    <RefreshCw className='h-4 w-4 animate-spin' />
                  ) : (
                    <Webhook className='h-4 w-4' />
                  )}
                  Re-register Webhooks
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                Fix broken or expired webhook push notification channels
              </TooltipContent>
            </Tooltip>
          )}

          {/* Re-authenticate */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant='outline'
                size='sm'
                className='gap-2'
                onClick={handleReauth}
                disabled={oauthPending}
                data-testid={`reauth-${integrationId}`}
              >
                {oauthPending ? (
                  <RefreshCw className='h-4 w-4 animate-spin' />
                ) : (
                  <KeyRound className='h-4 w-4' />
                )}
                Re-authenticate
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              Re-authenticate to update token scopes or refresh credentials
            </TooltipContent>
          </Tooltip>
        </div>
      </TooltipProvider>

      {/* Snipe-IT Webhook URL Dialog */}
      {isSnipeIt && (
        <Dialog
          open={webhookUrlDialogOpen}
          onOpenChange={setWebhookUrlDialogOpen}
        >
          <DialogContent className='max-w-lg'>
            <DialogHeader>
              <DialogTitle className='flex items-center gap-2'>
                <Link2 className='h-5 w-5' />
                Snipe-IT Webhook URL
              </DialogTitle>
              <DialogDescription>
                Configure this URL in your Snipe-IT instance under Admin &gt;
                Settings &gt; Webhooks.
              </DialogDescription>
            </DialogHeader>
            <div className='mt-4 space-y-4'>
              {webhookUrlData?.data?.attributes?.webhook_url ? (
                <div className='flex items-center gap-2'>
                  <code className='bg-muted flex-1 rounded-md px-3 py-2 text-sm break-all'>
                    {webhookUrlData.data.attributes.webhook_url}
                  </code>
                  <Button
                    variant='outline'
                    size='sm'
                    onClick={handleCopyWebhookUrl}
                    data-testid='copy-webhook-url'
                  >
                    <Copy className='h-4 w-4' />
                  </Button>
                </div>
              ) : (
                <p className='text-muted-foreground text-sm'>
                  Loading webhook URL…
                </p>
              )}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
