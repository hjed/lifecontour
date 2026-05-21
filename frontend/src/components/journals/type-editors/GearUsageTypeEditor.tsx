'use client';

import { useState, useId } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Wrench, Plus, Check, ChevronsUpDown } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

import type { GearUsageData } from '@/types/journals';
import type { GearItem } from '@/types/gearItems';
import { getGearItems, createGearItem } from '@/lib/api/gearItems';
import { useIntegrations } from '@/lib/api/integrations';
import {
  compactSummaryItems,
  GenericTypeEditorLayout,
} from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { format } from 'date-fns';

interface GearUsageTypeEditorProps {
  readonly journalId?: string;
  readonly data?: GearUsageData;
  readonly onSave?: (data: GearUsageData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: GearUsageData) => void;
}

const DEFAULT_DATA: GearUsageData = {};

export function GearUsageTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: GearUsageTypeEditorProps) {
  const baseId = useId();
  const [openCombobox, setOpenCombobox] = useState(false);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newGearItemName, setNewGearItemName] = useState('');
  const [isCreatingGearItem, setIsCreatingGearItem] = useState(false);

  const queryClient = useQueryClient();
  const { data: gearItems } = useQuery({
    queryKey: ['gear-items'],
    queryFn: () => getGearItems(),
  });

  const { data: integrationsResponse } = useIntegrations();
  const snipeItConnected =
    integrationsResponse?.data?.find(i => i.id === 'snipeit')?.attributes
      ?.status === 'connected';

  const {
    isEditing,
    editData,
    setEditData,
    handleEdit,
    handleSave,
    handleCancel,
  } = useTypeEditorState({
    initialData: data ?? DEFAULT_DATA,
    onSave,
    createMode,
    onChange,
  });

  const selectedGearItem = gearItems?.find(
    (g: GearItem) => g.id === editData.gear_item_id
  );

  const handleCreateGearItem = async () => {
    if (!newGearItemName.trim()) return;

    setIsCreatingGearItem(true);
    try {
      const newItem = await createGearItem({
        data: {
          type: 'gear-items',
          attributes: {
            name: newGearItemName.trim(),
          },
        },
      });
      await queryClient.invalidateQueries({ queryKey: ['gear-items'] });
      setEditData(prev => ({ ...prev, gear_item_id: newItem.id }));
      setCreateDialogOpen(false);
      setNewGearItemName('');
      toast.success('Gear item created');
    } catch {
      toast.error('Failed to create gear item');
    } finally {
      setIsCreatingGearItem(false);
    }
  };

  const safeFormatDate = (dateStr?: string | null) => {
    if (!dateStr) return null;
    try {
      const d = new Date(dateStr);
      return isNaN(d.getTime()) ? null : format(d, 'PP p');
    } catch {
      return null;
    }
  };

  const summaryItems = compactSummaryItems(
    selectedGearItem
      ? {
          label: 'Gear Item',
          value: selectedGearItem.name,
        }
      : null,
    snipeItConnected && editData?.checkout_date
      ? {
          label: 'Checkout Date',
          value: safeFormatDate(editData.checkout_date) || 'Invalid Date',
        }
      : null,
    snipeItConnected && editData?.checkin_date
      ? {
          label: 'Checkin Date',
          value: safeFormatDate(editData.checkin_date) || 'Invalid Date',
        }
      : null
  );

  const formatForInput = (isoString?: string | null) => {
    if (!isoString) return '';
    try {
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return '';
      // Offset by timezone
      const tzoffset = d.getTimezoneOffset() * 60000;
      return new Date(d.getTime() - tzoffset).toISOString().slice(0, 16);
    } catch {
      return '';
    }
  };

  const toIsoString = (localString?: string) => {
    if (!localString) return null;
    try {
      return new Date(localString).toISOString();
    } catch {
      return null;
    }
  };

  return (
    <>
      <GenericTypeEditorLayout
        className={className}
        testId={testId || 'gear-usage-type-editor'}
        createMode={createMode}
        isEditing={isEditing}
        emptyMessage='No gear usage details provided.'
        summaryItems={summaryItems}
        summaryTestId='gear-usage-summary'
        onEdit={handleEdit}
        onSave={async () => {
          if (!editData.gear_item_id) {
            toast.error('A gear item must be selected.');
            return;
          }
          if (
            editData.checkout_date &&
            editData.checkin_date &&
            new Date(editData.checkin_date) < new Date(editData.checkout_date)
          ) {
            toast.error('Checkin date cannot be before checkout date.');
            return;
          }
          await handleSave();
        }}
        onCancel={handleCancel}
      >
        <div className='space-y-4'>
          <div className='flex flex-col space-y-2'>
            <Label
              htmlFor={`${baseId}-gear-item`}
              className='flex items-center gap-2'
            >
              <Wrench
                className='text-muted-foreground h-4 w-4'
                aria-hidden='true'
              />
              Gear Item
            </Label>
            <Popover
              open={openCombobox && (isEditing || createMode)}
              onOpenChange={setOpenCombobox}
            >
              <PopoverTrigger asChild>
                <Button
                  id={`${baseId}-gear-item`}
                  variant='outline'
                  role='combobox'
                  aria-expanded={openCombobox && (isEditing || createMode)}
                  disabled={!isEditing && !createMode}
                  className='w-full justify-between'
                  data-testid='gear-item-selector'
                >
                  {selectedGearItem
                    ? selectedGearItem.name
                    : 'Select gear item...'}
                  <ChevronsUpDown className='ml-2 h-4 w-4 shrink-0 opacity-50' />
                </Button>
              </PopoverTrigger>
              <PopoverContent className='w-[400px] p-0' align='start'>
                <Command>
                  <CommandInput placeholder='Search gear items...' />
                  <CommandList>
                    <CommandEmpty className='flex flex-col items-center justify-center gap-2 p-2'>
                      <p className='text-muted-foreground text-sm'>
                        No gear item found.
                      </p>
                      <Button
                        variant='outline'
                        size='sm'
                        onClick={() => {
                          setOpenCombobox(false);
                          setCreateDialogOpen(true);
                        }}
                      >
                        <Plus className='mr-2 h-4 w-4' /> Create Gear Item
                      </Button>
                    </CommandEmpty>
                    <CommandGroup>
                      {gearItems?.map((item: GearItem) => (
                        <CommandItem
                          key={item.id}
                          value={item.name}
                          onSelect={() => {
                            setEditData(prev => ({
                              ...prev,
                              gear_item_id: item.id,
                            }));
                            setOpenCombobox(false);
                          }}
                        >
                          <Check
                            className={cn(
                              'mr-2 h-4 w-4',
                              editData.gear_item_id === item.id
                                ? 'opacity-100'
                                : 'opacity-0'
                            )}
                          />
                          {item.name}
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
          </div>

          {snipeItConnected && (
            <div className='grid gap-4 sm:grid-cols-2'>
              <div className='space-y-2'>
                <Label htmlFor={`${baseId}-checkout-date`}>
                  Checkout Date (Buffer)
                </Label>
                <Input
                  id={`${baseId}-checkout-date`}
                  data-testid='checkout-date-input'
                  type='datetime-local'
                  value={formatForInput(editData.checkout_date)}
                  onChange={e =>
                    setEditData(prev => ({
                      ...prev,
                      checkout_date: toIsoString(e.target.value),
                    }))
                  }
                  disabled={!isEditing && !createMode}
                />
              </div>
              <div className='space-y-2'>
                <Label htmlFor={`${baseId}-checkin-date`}>
                  Checkin Date (Buffer)
                </Label>
                <Input
                  id={`${baseId}-checkin-date`}
                  data-testid='checkin-date-input'
                  type='datetime-local'
                  value={formatForInput(editData.checkin_date)}
                  onChange={e =>
                    setEditData(prev => ({
                      ...prev,
                      checkin_date: toIsoString(e.target.value),
                    }))
                  }
                  disabled={!isEditing && !createMode}
                />
              </div>
            </div>
          )}
        </div>
      </GenericTypeEditorLayout>

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Gear Item</DialogTitle>
            <DialogDescription>
              Add a new gear item to your inventory.
            </DialogDescription>
          </DialogHeader>
          <div className='space-y-4 py-4'>
            <div className='space-y-2'>
              <Label htmlFor='new-gear-item-name'>Name</Label>
              <Input
                id='new-gear-item-name'
                value={newGearItemName}
                onChange={e => setNewGearItemName(e.target.value)}
                placeholder='e.g. Climbing Rope (60m)'
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant='outline'
              onClick={() => setCreateDialogOpen(false)}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreateGearItem}
              disabled={isCreatingGearItem || !newGearItemName.trim()}
            >
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
