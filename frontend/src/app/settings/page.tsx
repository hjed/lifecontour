'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { CalendarSettings } from '@/components/settings/CalendarSettings';
import { TimezoneSettings } from '@/components/settings/TimezoneSettings';
import { TemplateSettings } from '@/components/settings/TemplateSettings';

export default function SettingsPage() {
  return (
    <AuthGuard>
      <div className='container mx-auto py-8'>
        <div className='mb-8'>
          <h1 className='text-3xl font-bold tracking-tight'>Settings</h1>
          <p className='text-muted-foreground'>
            Manage your personal management system settings
          </p>
        </div>

        <div className='grid gap-6 lg:grid-cols-2'>
          <CalendarSettings />
          <TimezoneSettings />
          <TemplateSettings />
        </div>
      </div>
    </AuthGuard>
  );
}
