'use client';

import { useState } from 'react';
import { Calendar as CalendarIcon, Edit2, Trash2, Plus } from 'lucide-react';
import { useCalendars, useDeleteCalendar } from '@/lib/api/journals';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card';
import { LoadingSpinner } from '@/components/ui/loading';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { CalendarSettingsDialog } from './CalendarSettingsDialog';
import { JournalCalendar } from '@/types/journals';

export function CalendarSettings() {
  const { data, isLoading, error } = useCalendars();
  const { mutate: deleteCalendar, isPending: isDeleting } = useDeleteCalendar();

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingCalendar, setEditingCalendar] = useState<
    JournalCalendar | undefined
  >();

  const calendars = data?.data || [];

  const handleCreate = () => {
    setEditingCalendar(undefined);
    setIsDialogOpen(true);
  };

  const handleEdit = (calendar: JournalCalendar) => {
    setEditingCalendar(calendar);
    setIsDialogOpen(true);
  };

  const handleDelete = (id: string) => {
    if (globalThis.confirm('Are you sure you want to delete this calendar?')) {
      deleteCalendar(id);
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className='pt-6 text-center'>
          <LoadingSpinner size='md' text='Loading calendars...' />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className='pt-6'>
          <Alert variant='destructive'>
            <AlertDescription>
              Failed to load calendars: {error.message}
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card>
        <CardHeader className='flex flex-row items-center justify-between'>
          <div>
            <CardTitle className='flex items-center gap-2'>
              <CalendarIcon className='text-primary h-5 w-5' />
              Calendars
            </CardTitle>
            <CardDescription className='pt-1'>
              Manage calendars used to organize your journals and events.
            </CardDescription>
          </div>
          <Button onClick={handleCreate} size='sm'>
            <Plus className='mr-2 h-4 w-4' />
            Add Calendar
          </Button>
        </CardHeader>
        <CardContent>
          {calendars.length === 0 ? (
            <p className='text-muted-foreground py-4 text-center'>
              No calendars found. Create one to get started.
            </p>
          ) : (
            <div className='space-y-4'>
              {calendars.map(cal => {
                const calendarData: JournalCalendar = {
                  id: cal.id,
                  name: cal.attributes.name,
                  color: cal.attributes.color,
                  description: cal.attributes.description,
                  is_synced_to_google: cal.attributes.is_synced_to_google,
                  google_calendar_id: cal.attributes.google_calendar_id,
                };

                return (
                  <div
                    key={cal.id}
                    data-testid={`calendar-row-${cal.id}`}
                    className='flex items-center justify-between rounded-lg border p-3'
                  >
                    <div className='flex items-center gap-3'>
                      <div
                        className='h-4 w-4 rounded-full'
                        style={{
                          backgroundColor: calendarData.color || '#6b7280',
                        }}
                      />
                      <div>
                        <p className='text-sm font-medium'>
                          {calendarData.name}
                        </p>
                        {calendarData.description && (
                          <p className='text-muted-foreground text-xs'>
                            {calendarData.description}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className='flex items-center gap-2'>
                      <Button
                        variant='ghost'
                        size='sm'
                        onClick={() => handleEdit(calendarData)}
                        aria-label={`Edit calendar ${calendarData.name}`}
                      >
                        <Edit2 className='text-muted-foreground h-4 w-4' />
                      </Button>
                      <Button
                        variant='ghost'
                        size='sm'
                        onClick={() => handleDelete(cal.id)}
                        disabled={isDeleting}
                        aria-label={`Delete calendar ${calendarData.name}`}
                      >
                        <Trash2 className='text-destructive h-4 w-4' />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <CalendarSettingsDialog
        open={isDialogOpen}
        onOpenChange={setIsDialogOpen}
        calendar={editingCalendar}
      />
    </>
  );
}
