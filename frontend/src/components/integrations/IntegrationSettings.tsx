import { useState } from 'react';
import { Settings } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { CalendarSettings } from '@/components/settings/CalendarSettings';
import { StravaAthleteMappings } from '@/components/integrations/StravaAthleteMappings';
import { SnipeItSettings } from '@/components/integrations/SnipeItSettings';

export interface IntegrationSettingsProps {
  readonly integrationId: string;
}

export function IntegrationSettings({
  integrationId,
}: IntegrationSettingsProps) {
  const [open, setOpen] = useState(false);

  // In the future, this would fetch the dynamic settings schema from the registry
  // and render a dynamic form. For now, we hardcode the Google Calendar settings
  // for the Google integration to satisfy the requirement:
  // "Existing Google Calendar selection UI (CalendarSettingsDialog) accessible from the Google panel settings"

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant='outline' size='sm' className='gap-2'>
          <Settings className='h-4 w-4' />
          Settings
        </Button>
      </DialogTrigger>
      <DialogContent className='max-h-[90vh] max-w-3xl overflow-y-auto'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            <Settings className='h-5 w-5 text-gray-500' />
            Integration Settings
          </DialogTitle>
        </DialogHeader>

        <div className='mt-4'>
          {(() => {
            if (integrationId === 'google') {
              return (
                <div className='space-y-4'>
                  <div className='mb-6'>
                    <h3 className='text-lg font-medium'>
                      Calendar Sync Configuration
                    </h3>
                    <p className='text-muted-foreground text-sm'>
                      Map your local journals to specific Google Calendars here.
                    </p>
                  </div>
                  {/* Embed the existing Calendar Settings UI directly */}
                  <CalendarSettings />
                </div>
              );
            } else if (integrationId === 'strava') {
              return (
                <div className='space-y-4'>
                  <div className='mb-6'>
                    <h3 className='text-lg font-medium'>Athlete Mappings</h3>
                    <p className='text-muted-foreground text-sm'>
                      Manage the mappings between Strava athletes and CRM
                      contacts.
                    </p>
                  </div>
                  <StravaAthleteMappings />
                </div>
              );
            } else if (integrationId === 'snipeit') {
              return (
                <div className='space-y-4'>
                  <div className='mb-6'>
                    <h3 className='text-lg font-medium'>
                      Snipe-IT Configuration
                    </h3>
                    <p className='text-muted-foreground text-sm'>
                      Configure your Snipe-IT instance URL and user mapping.
                    </p>
                  </div>
                  <SnipeItSettings />
                </div>
              );
            } else {
              return (
                <div className='text-muted-foreground py-8 text-center'>
                  <p>No settings available for this integration.</p>
                  <p className='mt-2 text-sm'>
                    Dynamic schema rendering will be implemented here.
                  </p>
                </div>
              );
            }
          })()}
        </div>
      </DialogContent>
    </Dialog>
  );
}
