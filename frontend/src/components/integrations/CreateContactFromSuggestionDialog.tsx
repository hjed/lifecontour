'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';

const newContactSchema = z.object({
  first_name: z
    .string()
    .trim()
    .min(1, 'First name is required')
    .max(100, 'First name must be 100 characters or fewer'),
  last_name: z
    .string()
    .trim()
    .max(100, 'Last name must be 100 characters or fewer'),
});

export type NewContactNames = z.infer<typeof newContactSchema>;

/** Split a reported display name into first and last name defaults. */
export function namesFromDisplayName(
  displayName: string | null
): NewContactNames {
  const [first = '', ...rest] = (displayName ?? '').trim().split(/\s+/);
  return { first_name: first, last_name: rest.join(' ') };
}

interface CreateContactFromSuggestionDialogProps {
  readonly email: string;
  readonly displayName: string | null;
  readonly isSaving: boolean;
  readonly onCreate: (names: NewContactNames) => void;
  readonly onClose: () => void;
}

/**
 * Names a new contact for a suggested email. Rendered only while open, so the
 * form's defaults always come from the suggestion being accepted.
 */
export function CreateContactFromSuggestionDialog({
  email,
  displayName,
  isSaving,
  onCreate,
  onClose,
}: CreateContactFromSuggestionDialogProps) {
  const form = useForm<NewContactNames>({
    resolver: zodResolver(newContactSchema),
    defaultValues: namesFromDisplayName(displayName),
  });

  return (
    <Dialog open onOpenChange={open => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create contact</DialogTitle>
          <DialogDescription>
            A new contact with the email {email}, linked to every event it was
            seen on.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(onCreate)}
            className='space-y-4'
            data-testid='create-contact-from-suggestion-form'
          >
            <FormField
              control={form.control}
              name='first_name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>First name</FormLabel>
                  <FormControl>
                    <Input autoComplete='off' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='last_name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Last name</FormLabel>
                  <FormControl>
                    <Input autoComplete='off' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type='button' variant='outline' onClick={onClose}>
                Cancel
              </Button>
              <Button type='submit' disabled={isSaving}>
                {isSaving && <Loader2 className='mr-2 h-4 w-4 animate-spin' />}
                Create contact
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
