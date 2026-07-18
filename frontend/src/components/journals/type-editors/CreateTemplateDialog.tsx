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
import { createTemplate, updateTemplate } from '@/lib/api/templates';
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
  readonly template?: ActivityTemplateResource;
}

/**
 * Outer dialog wrapper. The inner form content remounts each time the
 * dialog opens so that `initialPitches`/`template` are always fresh via
 * `useState` on mount — no useEffect or useRef needed.
 *
 * When `template` is provided the dialog edits that template in place
 * (PUT) instead of creating a new one.
 */
export function CreateTemplateDialog({
  open,
  onOpenChange,
  defaultTemplateType,
  onCreated,
  initialPitches = [],
  template,
}: CreateTemplateDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && (
        <CreateTemplateDialogContent
          defaultTemplateType={defaultTemplateType}
          initialPitches={initialPitches}
          template={template}
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
  readonly template?: ActivityTemplateResource;
  readonly onCreated: (template: ActivityTemplateResource) => void;
  readonly onClose: () => void;
}

/**
 * Inner form content that mounts fresh each time the dialog opens.
 * This ensures `initialPitches`/`template` are always the current values.
 */
function CreateTemplateDialogContent({
  defaultTemplateType,
  initialPitches,
  template,
  onCreated,
  onClose,
}: CreateTemplateDialogContentProps) {
  const queryClient = useQueryClient();
  const isEditing = template != null;
  const [pitches, setPitches] = useState<TemplatePitch[]>(
    template?.attributes.pitches ?? initialPitches
  );

  const form = useForm<CreateTemplateFormValues>({
    resolver: zodResolver(createTemplateSchema),
    defaultValues: {
      name: template?.attributes.name ?? '',
      description: template?.attributes.description ?? '',
      region: template?.attributes.region ?? '',
      template_type:
        template?.attributes.template_type ??
        defaultTemplateType ??
        ActivityTemplateType.CANYONING,
    },
  });

  const mutation = useMutation({
    mutationFn: (values: CreateTemplateFormValues) => {
      const attributes = {
        name: values.name,
        template_type: values.template_type,
        description: values.description || null,
        region: values.region || null,
        pitches: pitches.length > 0 ? pitches : null,
      };

      if (isEditing) {
        return updateTemplate(template.id, {
          data: {
            type: 'activity-templates',
            id: template.id,
            attributes,
          },
        });
      }

      return createTemplate({
        data: {
          type: 'activity-templates',
          attributes,
        },
      });
    },
    onSuccess: response => {
      toast.success(
        isEditing
          ? 'Template updated successfully'
          : 'Template created successfully'
      );
      queryClient.invalidateQueries({ queryKey: ['templates'] });
      onCreated(response.data);
      onClose();
    },
    onError: error => {
      toast.error(
        isEditing ? 'Failed to update template' : 'Failed to create template'
      );
      console.error('Template save error:', error);
    },
  });

  const onSubmit = (values: CreateTemplateFormValues) => {
    mutation.mutate(values);
  };

  return (
    <DialogContent className='max-h-[90vh] overflow-y-auto sm:max-w-[600px]'>
      <DialogHeader>
        <DialogTitle>
          {isEditing ? 'Edit Template' : 'Create Template'}
        </DialogTitle>
        <DialogDescription>
          {isEditing
            ? 'Update this template used to populate your journal entries.'
            : 'Create a new template to quickly populate your journal entries.'}
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
              {(() => {
                if (mutation.isPending) {
                  return isEditing ? 'Saving...' : 'Creating...';
                }
                return isEditing ? 'Save Changes' : 'Create Template';
              })()}
            </Button>
          </DialogFooter>
        </form>
      </Form>
    </DialogContent>
  );
}
