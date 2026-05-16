'use client';

import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import * as z from 'zod';
import { TagResource } from '@/types/contacts';
import {
  useUpdateTag,
  useDeleteTag,
  useTags,
  useMergeTag,
} from '@/lib/api/contacts';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';

const formSchema = z.object({
  name: z.string().min(1, 'Name is required').max(50),
  color: z.string().optional(),
  description: z.string().max(255).optional(),
  parent_id: z.string().optional(),
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
  const { mutateAsync: mergeTag, isPending: isMerging } = useMergeTag();
  const { data: allTagsData } = useTags();

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showMergeConfirm, setShowMergeConfirm] = useState(false);
  const [mergeTargetId, setMergeTargetId] = useState<string>('');

  const allTags = allTagsData?.data ?? [];
  const validParentTags = allTags.filter(t => t.id !== tag.id); // Prevent self-parenting

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: tag.attributes.name,
      color: tag.attributes.color || '',
      description: tag.attributes.description || '',
      parent_id: tag.attributes.parent_id
        ? String(tag.attributes.parent_id)
        : 'none',
    },
  });

  // Reset form when tag changes
  React.useEffect(() => {
    if (open) {
      form.reset({
        name: tag.attributes.name,
        color: tag.attributes.color || '',
        description: tag.attributes.description || '',
        parent_id: tag.attributes.parent_id
          ? String(tag.attributes.parent_id)
          : 'none',
      });

      setMergeTargetId('');
      setShowMergeConfirm(false);
      setShowDeleteConfirm(false);
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
          parent_id:
            values.parent_id !== 'none'
              ? Number.parseInt(values.parent_id || '', 10)
              : null,
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

  const handleMerge = async () => {
    if (!mergeTargetId) return;
    try {
      await mergeTag({ sourceId: tag.id, targetId: mergeTargetId });
      setShowMergeConfirm(false);
      onOpenChange(false);
    } catch {
      // Error handled by mutation
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-[425px]'>
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
              name='parent_id'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Parent Tag</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder='Select a parent tag' />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value='none'>None (Root Level)</SelectItem>
                      {validParentTags.map(t => (
                        <SelectItem key={t.id} value={t.id}>
                          {t.attributes.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
                    disabled={isDeleting || isMerging}
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

              <Button type='submit' disabled={isUpdating || isMerging}>
                {isUpdating ? 'Saving...' : 'Save Changes'}
              </Button>
            </DialogFooter>
          </form>
        </Form>

        <Separator className='my-4' />

        <div className='space-y-4'>
          <div>
            <h4 className='text-sm font-medium'>Merge Tag</h4>
            <p className='text-muted-foreground mt-1 text-sm'>
              Merge this tag into another one. All contacts and child tags will
              be moved to the target tag, and this tag will be deleted.
            </p>
          </div>

          <div className='flex gap-2'>
            <Select onValueChange={setMergeTargetId} value={mergeTargetId}>
              <SelectTrigger className='flex-1'>
                <SelectValue placeholder='Select target tag to merge into' />
              </SelectTrigger>
              <SelectContent>
                {validParentTags.map(t => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.attributes.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <AlertDialog
              open={showMergeConfirm}
              onOpenChange={setShowMergeConfirm}
            >
              <AlertDialogTrigger asChild>
                <Button
                  type='button'
                  variant='secondary'
                  disabled={!mergeTargetId || isMerging}
                >
                  {isMerging ? 'Merging...' : 'Merge'}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Confirm Merge</AlertDialogTitle>
                  <AlertDialogDescription>
                    Are you sure you want to merge &quot;{tag.attributes.name}
                    &quot; into the selected tag? This action cannot be undone.
                    All contacts will be reassigned and this tag will be
                    deleted.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={handleMerge} disabled={isMerging}>
                    {isMerging ? 'Merging...' : 'Confirm Merge'}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
