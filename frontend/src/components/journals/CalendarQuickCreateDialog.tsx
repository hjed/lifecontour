import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { JournalCreateForm } from '@/components/journals/JournalCreateForm';
import { JournalType } from '@/types/journals';
import { parseISO } from 'date-fns';

interface CalendarQuickCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialDate?: string; // YYYY-MM-DD
  onSuccess?: (journalId: string) => void;
}

export function CalendarQuickCreateDialog({
  open,
  onOpenChange,
  initialDate,
  onSuccess,
}: CalendarQuickCreateDialogProps) {
  // When dialog opens, we want to update formKey only if it just opened
  // but we can just simplify it to forcing the key on render or using onOpenChange
  // If we just use quickCreateDate as key, that would update it but it changes string.
  // Actually, we can just use the key based on the initialDate string directly,
  // since it changes when the user clicks a different date.

  const parsedDate = initialDate ? parseISO(initialDate) : new Date();
  const currentKey = `${initialDate || 'new'}-${open ? 'open' : 'closed'}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle>Quick Create Event</DialogTitle>
          <DialogDescription>
            Create a new event journal directly from the calendar view.
          </DialogDescription>
        </DialogHeader>

        {open && (
          <div className='py-2'>
            <JournalCreateForm
              key={currentKey}
              initialTypes={[JournalType.EVENT]}
              initialDate={{ from: parsedDate, to: parsedDate }}
              onCancel={() => onOpenChange(false)}
              onSuccess={id => {
                onOpenChange(false);
                if (onSuccess) onSuccess(id);
              }}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
