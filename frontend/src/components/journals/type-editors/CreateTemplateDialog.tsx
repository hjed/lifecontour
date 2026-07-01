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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

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
  template_type: z.nativeEnum(ActivityTemplateType, {
    error: 'Template type is required',
  }),
});

type CreateTemplateFormValues = z.infer<typeof createTemplateSchema>;

interface CreateTemplateDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly defaultTemplateType?: ActivityTemplateType;
  readonly onCreated: (template: ActivityTemplateResource) => void;
  readonly initialPitches?: TemplatePitch[];
}

/**
 * Outer dialog wrapper. The inner form content remounts each time the
 * dialog opens so that `initialPitches` is always fresh via `useState`
 * on mount — no useEffect or useRef needed.
 */
export function CreateTemplateDialog({
  open,
  onOpenChange,
  defaultTemplateType,
  onCreated,
  initialPitches = [],
}: CreateTemplateDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && (
        <CreateTemplateDialogContent
          defaultTemplateType={defaultTemplateType}
          initialPitches={initialPitches}
          onCreated={onCreated}
          onClose={() => onOpenChange(false)}
        />
      )}
    </Dialog>
  );
}

interface CreateTemplateDialogContentProps {
  readonly defaultTemplateType?: ActivityTemplateType;
  readonly initialPitches: TemplatePitch[];
  readonly onCreated: (template: ActivityTemplateResource) => void;
  readonly onClose: () => void;
}

/**
 * Inner form content that mounts fresh each time the dialog opens.
 * This ensures `initialPitches` is always the current value.
 */
function CreateTemplateDialogContent({
  defaultTemplateType,
  initialPitches,
  onCreated,
  onClose,
}: CreateTemplateDialogContentProps) {
  const queryClient = useQueryClient();
  const [pitches, setPitches] = useState<TemplatePitch[]>(initialPitches);

  const form = useForm<CreateTemplateFormValues>({
    resolver: zodResolver(createTemplateSchema),
    defaultValues: {
      name: '',
      description: '',
      region: '',
      template_type: defaultTemplateType || ActivityTemplateType.CANYONING,
    },
  });

  const mutation = useMutation({
    mutationFn: (values: CreateTemplateFormValues) => {
      return createTemplate({
        data: {
          type: 'activity-templates',
          attributes: {
            name: values.name,
            template_type: values.template_type,
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
      onCreated(response.data);
      onClose();
    },
    onError: error => {
      toast.error('Failed to create template');
      console.error('Template creation error:', error);
    },
  });

  const onSubmit = (values: CreateTemplateFormValues) => {
    mutation.mutate(values);
  };

  return (
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
            name='template_type'
            render={({ field }) => (
              <FormItem>
                <FormLabel>Template Type</FormLabel>
                <Select
                  onValueChange={field.onChange}
                  defaultValue={field.value}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder='Select a template type' />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value={ActivityTemplateType.CANYONING}>
                      Canyoning
                    </SelectItem>
                    <SelectItem value={ActivityTemplateType.CAVING}>
                      Caving
                    </SelectItem>
                    <SelectItem value={ActivityTemplateType.CLIMBING}>
                      Climbing
                    </SelectItem>
                    <SelectItem value={ActivityTemplateType.ABSEILING}>
                      Abseiling
                    </SelectItem>
                  </SelectContent>
                </Select>
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
              onClick={onClose}
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
  );
}
