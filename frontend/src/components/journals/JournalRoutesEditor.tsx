'use client';

import { useRef, useState } from 'react';
import { Upload, X, MapPin } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useRoutes, useCreateRoute } from '@/lib/api/routes';

interface JournalRoutesEditorProps {
  /** If in create mode, we manage internal state instead of API */
  readonly createMode?: boolean;
  /** Journal ID required if not in create mode */
  readonly journalId?: string;
  /** Internal routes controlled by parent if in create mode */
  readonly pendingRoutes?: { name: string; gpx_data: string }[];
  /** Callback to update parent routes if in create mode */
  readonly onPendingRoutesChange?: (
    routes: { name: string; gpx_data: string }[]
  ) => void;
  /** Whether the component is currently in edit state (hides upload UI if false) */
  readonly isEditing?: boolean;
}

export function JournalRoutesEditor({
  createMode = false,
  journalId,
  pendingRoutes = [],
  onPendingRoutesChange,
  isEditing = true,
}: JournalRoutesEditorProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);

  // API Hooks (only active if !createMode and journalId is present)
  const { data: routesData, isLoading: isLoadingRoutes } = useRoutes(
    journalId ?? '',
    {},
    { enabled: !createMode && !!journalId }
  );

  const createRouteMutation = useCreateRoute();

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    setIsUploading(true);

    try {
      const newRoutes: { name: string; gpx_data: string }[] = [];

      for (const file of files) {
        const content = await file.text();
        const routeName = file.name.replace(/\.gpx$/i, '');

        if (createMode) {
          newRoutes.push({ name: routeName, gpx_data: content });
        } else if (journalId) {
          // In edit mode, we send it directly to the API
          await createRouteMutation.mutateAsync({
            journalId,
            data: {
              name: routeName,
              gpx_data: content,
            },
          });
        }
      }

      if (createMode && newRoutes.length > 0 && onPendingRoutesChange) {
        onPendingRoutesChange([...pendingRoutes, ...newRoutes]);
      }

      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    } catch (error) {
      console.error('Failed to read or upload GPX file', error);
      toast.error('Failed to process GPX file');
    } finally {
      setIsUploading(false);
    }
  };

  const handleRemovePending = (indexToRemove: number) => {
    if (onPendingRoutesChange) {
      onPendingRoutesChange(
        pendingRoutes.filter((_, i) => i !== indexToRemove)
      );
    }
  };

  // If we're not editing and there are no routes (in either mode), don't show anything
  const hasLiveRoutes = routesData?.data && routesData.data.length > 0;
  const hasPendingRoutes = pendingRoutes.length > 0;

  if (!isEditing && !hasLiveRoutes && !hasPendingRoutes) {
    return null;
  }

  return (
    <div className='space-y-4' data-testid='journal-routes-editor'>
      <Label className='flex items-center gap-2'>
        <MapPin className='text-muted-foreground h-4 w-4' aria-hidden='true' />
        GPX Tracks
      </Label>

      {/* Render list of routes */}
      <div className='flex flex-col gap-2'>
        {createMode ? (
          // Create Mode: Render pending routes
          pendingRoutes.map((route, index) => (
            <div
              key={index}
              className='bg-muted/30 flex items-center justify-between rounded border p-2 text-sm'
            >
              <span className='truncate font-medium'>{route.name}</span>
              {isEditing && (
                <Button
                  type='button'
                  variant='ghost'
                  size='sm'
                  onClick={() => handleRemovePending(index)}
                  className='text-muted-foreground hover:text-destructive h-8 w-8 p-0'
                >
                  <X className='h-4 w-4' />
                </Button>
              )}
            </div>
          ))
        ) : (
          // Edit/View Mode: Render live routes
          <>
            {isLoadingRoutes && (
              <p className='text-muted-foreground text-sm'>Loading routes...</p>
            )}
            {routesData?.data.map(route => (
              <div
                key={route.id}
                className='bg-muted/30 flex items-center justify-between rounded border p-2 text-sm'
              >
                <span className='truncate font-medium'>
                  {route.attributes.name}
                </span>
                {/* Deleting routes is out of scope for the immediate editor UI unless requested, but could add a hook here */}
              </div>
            ))}
          </>
        )}
      </div>

      {/* Upload UI */}
      {isEditing && (
        <div className='mt-2 flex items-center gap-4'>
          <Button
            type='button'
            variant='outline'
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
            data-testid='gpx-multi-upload-btn'
          >
            <Upload className='mr-2 h-4 w-4' aria-hidden='true' />
            {isUploading ? 'Processing...' : 'Add GPX Tracks'}
          </Button>
          <Input
            type='file'
            accept='.gpx'
            multiple
            className='hidden'
            ref={fileInputRef}
            onChange={handleFileUpload}
            data-testid='gpx-multi-file-input'
          />
          <span className='text-muted-foreground text-sm'>
            Select one or more .gpx files
          </span>
        </div>
      )}
    </div>
  );
}
