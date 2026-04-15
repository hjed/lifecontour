'use client';

import { useState } from 'react';
import { Calendar, Cake, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useUpdateContact } from '@/lib/api/contacts';
import {
  ContactAttributes,
  ContactFormData,
  ImportantDateAttributes,
  ImportantDatePrecision,
  ImportantDateResource,
  ImportantDateTypeEnum,
} from '@/types/contacts';
import { ImportantDateInlineEditor } from './ImportantDateInlineEditor';
// uuid not needed anymore

export interface ImportantDatesListProps {
  readonly contactId: string;
  readonly contactAttributes: ContactAttributes;
  readonly disabled?: boolean;
}

export function ImportantDatesList({
  contactId,
  contactAttributes,
  disabled = false,
}: ImportantDatesListProps) {
  const [isAddingDate, setIsAddingDate] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [dateToDelete, setDateToDelete] = useState<string | null>(null);

  const updateContactMutation = useUpdateContact();
  const dates = contactAttributes.important_dates || [];

  const handleCreateOrUpdate = async (
    updatedDates: ImportantDateResource[]
  ) => {
    const data: ContactFormData = {
      first_name: contactAttributes.first_name,
      last_name: contactAttributes.last_name,
      middle_name: contactAttributes.middle_name,
      nick_name: contactAttributes.nick_name,
      contact_methods: contactAttributes.contact_methods || [],
      addresses: contactAttributes.addresses || [],
      notes: contactAttributes.notes || [],
      important_dates: updatedDates,
    };

    return updateContactMutation.mutateAsync({ id: contactId, data });
  };

  const handleAddDate = async (attributes: ImportantDateAttributes) => {
    const newResource: ImportantDateResource = {
      type: 'important_dates',
      attributes,
    };

    await handleCreateOrUpdate([...dates, newResource]);
    setIsAddingDate(false);
  };

  const handleDeleteClick = (dateId: string) => {
    setDateToDelete(dateId);
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!dateToDelete) return;
    const remainingDates = dates.filter(
      d => d.id?.toString() !== dateToDelete.toString()
    );
    await handleCreateOrUpdate(remainingDates);
    setDeleteDialogOpen(false);
    setDateToDelete(null);
  };

  const formatDisplay = (attr: ImportantDateAttributes) => {
    const parts = [];
    if (
      attr.precision === ImportantDatePrecision.FULL ||
      attr.precision === ImportantDatePrecision.DAY_MONTH
    ) {
      parts.push(`${attr.day || '?'} ${getMonthName(attr.month)}`);
    }
    if (
      attr.precision === ImportantDatePrecision.FULL ||
      attr.precision === ImportantDatePrecision.YEAR
    ) {
      parts.push(`${attr.year || '?'}`);
    }
    return parts.join(' ');
  };

  const getMonthName = (m?: number | null) => {
    if (!m || m < 1 || m > 12) return '???';
    const date = new Date(2000, m - 1, 1);
    return date.toLocaleString('default', { month: 'long' });
  };

  const getTypeDisplay = (type: string, customName?: string) => {
    if (type === ImportantDateTypeEnum.CUSTOM && customName) return customName;
    return type.replace(/_/g, ' ');
  };

  return (
    <Card className='flex h-full flex-col'>
      <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
        <CardTitle className='text-sm font-medium'>Important Dates</CardTitle>
        <Button
          variant='ghost'
          size='sm'
          className='h-8 w-8 p-0'
          onClick={() => setIsAddingDate(true)}
          disabled={disabled || updateContactMutation.isPending || isAddingDate}
          aria-label='Add important date'
        >
          <Plus className='h-4 w-4' />
        </Button>
      </CardHeader>
      <CardContent>
        <div className='space-y-4'>
          {dates.length === 0 && !isAddingDate && (
            <p className='text-muted-foreground text-sm italic'>
              No important dates yet. Click the + button to add one.
            </p>
          )}

          {dates.map((date, index) => {
            const isBirthday =
              date.attributes.date_type === ImportantDateTypeEnum.BIRTHDAY;
            return (
              <div
                key={date.id || `temp-${index}`}
                className={`flex items-center justify-between rounded-md border p-2 ${isBirthday ? 'bg-primary/5 border-primary/20' : 'bg-background'}`}
              >
                <div className='flex items-center gap-3'>
                  {isBirthday ? (
                    <Cake className='text-primary h-4 w-4' />
                  ) : (
                    <Calendar className='text-muted-foreground h-4 w-4' />
                  )}
                  <div className='flex flex-col'>
                    <span className='text-muted-foreground text-xs capitalize'>
                      {getTypeDisplay(
                        date.attributes.date_type,
                        date.attributes.custom_date_type_name || undefined
                      )}
                    </span>
                    <span
                      className={`text-sm ${isBirthday ? 'text-primary font-medium' : 'font-medium'}`}
                    >
                      {formatDisplay(date.attributes)}
                    </span>
                  </div>
                </div>

                <div className='flex gap-1'>
                  <Button
                    variant='ghost'
                    size='sm'
                    className='text-destructive hover:bg-destructive/10 hover:text-destructive h-8 w-8 p-0'
                    onClick={() =>
                      date.id && handleDeleteClick(date.id.toString())
                    }
                    disabled={disabled || updateContactMutation.isPending}
                    aria-label={`Delete ${date.attributes.date_type}`}
                  >
                    <Trash2 className='h-4 w-4' />
                  </Button>
                </div>
              </div>
            );
          })}

          {isAddingDate && (
            <ImportantDateInlineEditor
              onSave={handleAddDate}
              onCancel={() => setIsAddingDate(false)}
              isLoading={updateContactMutation.isPending}
            />
          )}
        </div>
      </CardContent>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Important Date</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this date? This action cannot be
              undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant='outline'
              onClick={() => setDeleteDialogOpen(false)}
              disabled={updateContactMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant='destructive'
              onClick={handleConfirmDelete}
              disabled={updateContactMutation.isPending}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
