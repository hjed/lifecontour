'use client';

import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { TagResource } from '@/types/contacts';
import { useUpdateTag, useDeleteTag } from '@/lib/api/contacts';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
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

export interface TagManagementDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly tag: TagResource;
}

export function TagManagementDialog({
  open,
  onOpenChange,
  tag,
}: TagManagementDialogProps) {
  const { mutateAsync: updateTag, isPending: isUpdating } = useUpdateTag();
  const { mutateAsync: deleteTag, isPending: isDeleting } = useDeleteTag();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: tag.attributes.name,
      color: tag.attributes.color || '',
      description: tag.attributes.description || '',
    },
  });

  // Reset form when tag changes
  React.useEffect(() => {
    if (open) {
      form.reset({
        name: tag.attributes.name,
        color: tag.attributes.color || '',
        description: tag.attributes.description || '',
      });
    }
  }, [tag, open, form]);

  const onSubmit = async (values: FormValues) => {
    try {
      await updateTag({
        id: tag.id,
        attributes: {
          name: values.name,
          color: values.color || '',
          description: values.description || '',
        },
      });
      onOpenChange(false);
    } catch {
      // Error is handled by the mutation's onError via toast
    }
  };

  const handleDelete = async () => {
    try {
      await deleteTag(tag.id);
      setShowDeleteConfirm(false);
      onOpenChange(false);
    } catch {
      // Error handled by mutation
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-[425px]'>
        <DialogHeader>
          <DialogTitle>Edit Tag</DialogTitle>
          <DialogDescription>
            Make changes to your tag here. Click save when you&apos;re done.
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

            <DialogFooter className='flex-row pt-4 sm:justify-between'>
              <AlertDialog
                open={showDeleteConfirm}
                onOpenChange={setShowDeleteConfirm}
              >
                <AlertDialogTrigger asChild>
                  <Button
                    type='button'
                    variant='destructive'
                    disabled={isDeleting}
                  >
                    {isDeleting ? 'Deleting...' : 'Delete Tag'}
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>
                      Are you absolutely sure?
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                      This action cannot be undone. This will permanently delete
                      the tag &quot;{tag.attributes.name}&quot; and remove it
                      from all associated contacts.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={handleDelete}
                      disabled={isDeleting}
                      className='bg-destructive text-destructive-foreground hover:bg-destructive/90'
                    >
                      {isDeleting ? 'Deleting...' : 'Delete'}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>

              <Button type='submit' disabled={isUpdating}>
                {isUpdating ? 'Saving...' : 'Save Changes'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
