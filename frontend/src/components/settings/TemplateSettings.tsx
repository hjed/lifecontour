'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { BookTemplate, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { LoadingSpinner } from '@/components/ui/loading';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { ActivityTemplateResource } from '@/types/journals';
import { getTemplates, deleteTemplate } from '@/lib/api/templates';
import { toast } from 'sonner';

export function TemplateSettings() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ['templates'],
    queryFn: () => getTemplates(),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteTemplate,
    onSuccess: () => {
      toast.success('Template deleted successfully');
      queryClient.invalidateQueries({ queryKey: ['templates'] });
    },
    onError: () => {
      toast.error('Failed to delete template');
    },
  });

  const [templateToDelete, setTemplateToDelete] =
    useState<ActivityTemplateResource | null>(null);

  const templates = data?.data || [];

  const handleDeleteClick = (template: ActivityTemplateResource) => {
    setTemplateToDelete(template);
  };

  const handleDeleteDialogChange = (open: boolean) => {
    if (!open) {
      setTemplateToDelete(null);
    }
  };

  const handleConfirmDelete = async () => {
    if (!templateToDelete) {
      return;
    }

    try {
      await deleteMutation.mutateAsync(templateToDelete.id);
    } finally {
      setTemplateToDelete(null);
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className='pt-6 text-center'>
          <LoadingSpinner size='md' text='Loading templates...' />
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
              Failed to load templates: {error.message}
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card id='templates' className='scroll-mt-20'>
        <CardHeader className='flex flex-row items-center justify-between'>
          <div>
            <CardTitle className='flex items-center gap-2'>
              <BookTemplate className='text-primary h-5 w-5' />
              Activity Templates
            </CardTitle>
            <CardDescription className='pt-1'>
              Manage templates used to populate activity details.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {templates.length === 0 ? (
            <p className='text-muted-foreground py-4 text-center'>
              No templates found. Create one from a journal editor to get
              started.
            </p>
          ) : (
            <div className='space-y-4'>
              {templates.map(template => (
                <div
                  key={template.id}
                  data-testid={`template-row-${template.id}`}
                  className='flex items-center justify-between rounded-lg border p-3'
                >
                  <div className='flex items-center gap-3'>
                    <div>
                      <p className='text-sm font-medium'>
                        {template.attributes.name}
                      </p>
                      <p className='text-muted-foreground text-xs uppercase'>
                        {template.attributes.template_type}
                        {template.attributes.region &&
                          ` • ${template.attributes.region}`}
                      </p>
                    </div>
                  </div>
                  <div className='flex items-center gap-2'>
                    <Button
                      variant='ghost'
                      size='sm'
                      onClick={() => handleDeleteClick(template)}
                      disabled={deleteMutation.isPending}
                      aria-label={`Delete template ${template.attributes.name}`}
                    >
                      <Trash2 className='text-destructive h-4 w-4' />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={templateToDelete !== null}
        onOpenChange={handleDeleteDialogChange}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete Template</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete the template &quot;
              {templateToDelete?.attributes.name}&quot;? This action cannot be
              undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant='outline'
              onClick={() => setTemplateToDelete(null)}
              disabled={deleteMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant='destructive'
              onClick={handleConfirmDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
