'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

import {
  ActivityTemplateType,
  ActivityTemplateResource,
  TemplatePitch,
} from '@/types/journals';
import { createTemplate } from '@/lib/api/templates';
import { PitchEditor } from './PitchEditor';

const createTemplateSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  description: z.string().optional(),
  region: z.string().optional(),
});

type CreateTemplateFormValues = z.infer<typeof createTemplateSchema>;

interface CreateTemplateDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly templateType: ActivityTemplateType;
  readonly onCreated: (template: ActivityTemplateResource) => void;
}

export function CreateTemplateDialog({
  open,
  onOpenChange,
  templateType,
  onCreated,
}: CreateTemplateDialogProps) {
  const queryClient = useQueryClient();
  const [pitches, setPitches] = useState<TemplatePitch[]>([]);

  const form = useForm<CreateTemplateFormValues>({
    resolver: zodResolver(createTemplateSchema),
    defaultValues: {
      name: '',
      description: '',
      region: '',
    },
  });

  const mutation = useMutation({
    mutationFn: (values: CreateTemplateFormValues) => {
      return createTemplate({
        data: {
          type: 'activity-templates',
          attributes: {
            name: values.name,
            template_type: templateType,
            description: values.description || null,
            region: values.region || null,
            pitches: pitches.length > 0 ? pitches : null,
          },
        },
      });
    },
    onSuccess: response => {
      toast.success('Template created successfully');
      queryClient.invalidateQueries({ queryKey: ['templates'] });
      form.reset();
      setPitches([]);
      onCreated(response.data);
      onOpenChange(false);
    },
    onError: error => {
      toast.error('Failed to create template');
      console.error('Template creation error:', error);
    },
  });

  const onSubmit = (values: CreateTemplateFormValues) => {
    mutation.mutate(values);
  };

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      form.reset();
      setPitches([]);
    }
    onOpenChange(newOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-[600px]'>
        <DialogHeader>
          <DialogTitle>Create Template</DialogTitle>
          <DialogDescription>
            Create a new template to quickly populate your journal entries.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className='space-y-4'>
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Template Name</FormLabel>
                  <FormControl>
                    <Input placeholder='e.g. Kowmung River Canyon' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='region'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Region</FormLabel>
                  <FormControl>
                    <Input placeholder='e.g. Blue Mountains' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name='description'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description (Optional)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder='Any notes about this template...'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className='pt-2'>
              <h4 className='mb-2 text-sm font-medium'>Standard Pitches</h4>
              <PitchEditor
                pitches={pitches}
                isEditing={true}
                onChange={setPitches}
              />
            </div>

            <DialogFooter className='pt-4'>
              <Button
                type='button'
                variant='outline'
                onClick={() => handleOpenChange(false)}
                disabled={mutation.isPending}
              >
                Cancel
              </Button>
              <Button type='submit' disabled={mutation.isPending}>
                {mutation.isPending ? 'Creating...' : 'Create Template'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
