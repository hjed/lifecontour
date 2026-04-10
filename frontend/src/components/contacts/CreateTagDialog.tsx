'use client';

import React from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { useCreateTag } from '@/lib/api/contacts';
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
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

const formSchema = z.object({
  name: z.string().min(1, 'Name is required').max(50),
  color: z.string().optional(),
  description: z.string().max(255).optional(),
});

type FormValues = z.infer<typeof formSchema>;

export interface CreateTagDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly parentId?: number; // Optional parent tag
}

export function CreateTagDialog({
  open,
  onOpenChange,
  parentId,
}: CreateTagDialogProps) {
  const { mutateAsync: createTag, isPending: isCreating } = useCreateTag();

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: '',
      color: '#000000',
      description: '',
    },
  });

  // Reset form when dialog opens
  React.useEffect(() => {
    if (open) {
      form.reset({
        name: '',
        color: '#000000',
        description: '',
      });
    }
  }, [open, form]);

  const onSubmit = async (values: FormValues) => {
    try {
      await createTag({
        name: values.name,
        color: values.color || undefined,
        description: values.description || undefined,
        parent_id: parentId,
      });
      onOpenChange(false);
    } catch {
      // Error handled by mutation
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-[425px]'>
        <DialogHeader>
          <DialogTitle>Create Tag</DialogTitle>
          <DialogDescription>
            Add a new tag to organize your contacts.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className='space-y-4'>
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder='Tag name' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='color'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Color</FormLabel>
                  <div className='flex items-center gap-2'>
                    <Input
                      type='color'
                      className='h-10 w-12 p-1'
                      value={field.value || '#000000'}
                      onChange={e => field.onChange(e.target.value)}
                      aria-label='Color Picker'
                    />
                    <FormControl>
                      <Input placeholder='#000000' {...field} />
                    </FormControl>
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='description'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea placeholder='Optional description' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter className='pt-4'>
              <Button
                type='button'
                variant='outline'
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button type='submit' disabled={isCreating}>
                {isCreating ? 'Creating...' : 'Create Tag'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
