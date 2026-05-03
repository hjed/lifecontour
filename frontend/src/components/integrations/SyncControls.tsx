'use client';

import { ChevronDown, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useGenericSync } from '@/lib/api/integrations';

interface SyncButtonProps {
  integrationId: string;
  capability: string;
  disabled: boolean;
  label?: string;
  testId?: string;
}

function SyncButton({
  integrationId,
  capability,
  disabled,
  label,
  testId,
}: SyncButtonProps) {
  const { mutate: triggerSync, isPending: syncLoading } = useGenericSync(
    integrationId,
    capability
  );

  const formattedCapability = capability
    .replace('_sync', '')
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
  const displayLabel = label || `Sync ${formattedCapability}`;
  const baseTestId = testId || `trigger-${capability}-sync`;

  return (
    <div className='flex items-center'>
      <Button
        className='border-primary-foreground/20 rounded-r-none border-r'
        onClick={() => triggerSync('smart')}
        disabled={disabled || syncLoading}
        data-testid={baseTestId}
      >
        {syncLoading ? (
          <RefreshCw className='mr-2 h-4 w-4 animate-spin' />
        ) : (
          <RefreshCw className='mr-2 h-4 w-4' />
        )}
        {displayLabel}
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            className='rounded-l-none px-2'
            disabled={disabled || syncLoading}
            data-testid={`${baseTestId}-dropdown`}
          >
            <ChevronDown className='h-4 w-4' />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end'>
          <DropdownMenuItem
            onClick={() => triggerSync('smart')}
            data-testid={`${baseTestId}-smart`}
          >
            Smart Sync (Fast)
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => triggerSync('full')}
            data-testid={`${baseTestId}-full`}
          >
            Full Sync (Comprehensive)
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

interface SyncControlsProps {
  integrationId: string;
  capabilities: string[];
  connected: boolean;
  needsReauth?: boolean;
  needsReconsent?: boolean;
}

export function SyncControls({
  integrationId,
  capabilities,
  connected,
  needsReauth,
  needsReconsent,
}: SyncControlsProps) {
  if (!connected) return null;

  const syncDisabled = !!needsReauth || !!needsReconsent;

  return (
    <div className='flex flex-wrap gap-2'>
      {capabilities.map(capability => (
        <SyncButton
          key={capability}
          integrationId={integrationId}
          capability={capability}
          disabled={syncDisabled}
          testId={`trigger-${integrationId}-${capability.replace('_sync', '')}-sync`}
        />
      ))}
      <div className='text-muted-foreground mt-2 w-full text-xs'>
        Full sync is automatically triggered when necessary. Use the sync
        buttons to update latest changes.
      </div>
    </div>
  );
}
