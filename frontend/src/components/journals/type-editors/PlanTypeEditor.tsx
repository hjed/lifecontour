/**
 * PlanTypeEditor component for editing PLAN type journal data.
 *
 * Provides inline editing for plan documents with add/remove/reorder functionality.
 */

'use client';

import { useCallback, useState } from 'react';
import { ClipboardList, Plus, Trash2 } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import type { PlanData, PlanDocument } from '@/types/journals';

interface PlanTypeEditorProps {
  readonly journalId: string;
  readonly data?: PlanData;
  readonly onSave?: (data: PlanData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
}

/**
 * PlanTypeEditor component for editing plan documents.
 *
 * @example
 * ```tsx
 * <PlanTypeEditor
 *   journalId="123"
 *   data={planData}
 *   onSave={handleSave}
 * />
 * ```
 */
export function PlanTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
}: PlanTypeEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editData, setEditData] = useState<PlanData>(
    data || {
      documents: [],
    }
  );

  const handleSave = useCallback(async () => {
    if (onSave) {
      await onSave(editData);
      setIsEditing(false);
    }
  }, [editData, onSave]);

  const handleCancel = useCallback(() => {
    setEditData(
      data || {
        documents: [],
      }
    );
    setIsEditing(false);
  }, [data]);

  const handleAddDocument = useCallback(() => {
    setEditData({
      ...editData,
      documents: [
        ...editData.documents,
        {
          url: '',
          title: null,
          description: null,
          order: editData.documents.length,
        },
      ],
    });
  }, [editData]);

  const handleRemoveDocument = useCallback(
    (index: number) => {
      setEditData({
        ...editData,
        documents: editData.documents.filter((_, i) => i !== index),
      });
    },
    [editData]
  );

  const handleUpdateDocument = useCallback(
    (index: number, field: keyof PlanDocument, value: string) => {
      const updatedDocuments = [...editData.documents];
      updatedDocuments[index] = {
        ...updatedDocuments[index],
        [field]: value || null,
      };
      setEditData({
        ...editData,
        documents: updatedDocuments,
      });
    },
    [editData]
  );

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid={testId || 'plan-type-editor'}
    >
      {/* Documents List */}
      <div className='space-y-3'>
        <Label className='flex items-center gap-2'>
          <ClipboardList className='h-4 w-4' aria-hidden='true' />
          Plan Documents
        </Label>

        {editData.documents.length === 0 ? (
          <p className='text-muted-foreground text-sm'>
            No documents added yet
          </p>
        ) : (
          <div className='space-y-3'>
            {editData.documents.map((doc, index) => (
              <div
                key={index}
                className='space-y-2 rounded-md border p-3'
                data-testid={`document-${index}`}
              >
                <div className='flex items-start justify-between gap-2'>
                  <div className='flex-1 space-y-2'>
                    <Input
                      value={doc.url}
                      onChange={e =>
                        handleUpdateDocument(index, 'url', e.target.value)
                      }
                      placeholder='Document URL'
                      disabled={!isEditing}
                      data-testid={`document-url-${index}`}
                    />
                    <Input
                      value={doc.title || ''}
                      onChange={e =>
                        handleUpdateDocument(index, 'title', e.target.value)
                      }
                      placeholder='Document title (optional)'
                      disabled={!isEditing}
                      data-testid={`document-title-${index}`}
                    />
                    <Textarea
                      value={doc.description || ''}
                      onChange={e =>
                        handleUpdateDocument(
                          index,
                          'description',
                          e.target.value
                        )
                      }
                      placeholder='Description (optional)'
                      disabled={!isEditing}
                      rows={2}
                      data-testid={`document-description-${index}`}
                    />
                  </div>
                  {isEditing && (
                    <Button
                      variant='ghost'
                      size='sm'
                      onClick={() => handleRemoveDocument(index)}
                      aria-label='Remove document'
                      data-testid={`remove-document-${index}`}
                    >
                      <Trash2 className='h-4 w-4' />
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {isEditing && (
          <Button
            variant='outline'
            size='sm'
            onClick={handleAddDocument}
            className='w-full'
            data-testid='add-document-button'
          >
            <Plus className='mr-2 h-4 w-4' />
            Add Document
          </Button>
        )}
      </div>

      {/* Edit/Save/Cancel buttons */}
      <div className='flex gap-2'>
        {!isEditing ? (
          <Button
            variant='outline'
            size='sm'
            onClick={() => setIsEditing(true)}
            data-testid='edit-button'
          >
            Edit
          </Button>
        ) : (
          <>
            <Button
              variant='default'
              size='sm'
              onClick={handleSave}
              data-testid='save-button'
            >
              Save
            </Button>
            <Button
              variant='outline'
              size='sm'
              onClick={handleCancel}
              data-testid='cancel-button'
            >
              Cancel
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
