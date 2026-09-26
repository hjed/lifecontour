'use client';

import { useState, useId } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Wrench, Plus, ChevronsUpDown, X } from 'lucide-react';
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

import type { GearUsageData, GearUsageItem } from '@/types/journals';
import type { GearItem } from '@/types/gearItems';
import { getGearItems, createGearItem } from '@/lib/api/gearItems';
import { useIntegrations } from '@/lib/api/integrations';
import {
  compactSummaryItems,
  GenericTypeEditorLayout,
} from './GenericTypeEditorLayout';
import { gearUsageItems, gearUsageItemsError } from './gearUsageItems';
import { useTypeEditorState } from './useTypeEditorState';
import { toast } from 'sonner';
import { format } from 'date-fns';
import { invalidateAfterMutation } from '@/lib/api/invalidate-after-mutation';

interface GearUsageTypeEditorProps {
  readonly journalId?: string;
  readonly data?: GearUsageData;
  readonly onSave?: (data: GearUsageData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: GearUsageData) => void;
}

type ItemDateField = 'checkout_date' | 'checkin_date';

function safeFormatDate(dateStr?: string | null): string | null {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  return Number.isNaN(d.getTime()) ? null : format(d, 'PP p');
}

/** An ISO instant as a `datetime-local` value in the browser's zone. */
function formatForInput(isoString?: string | null): string {
  if (!isoString) return '';
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return '';
  const tzoffset = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - tzoffset).toISOString().slice(0, 16);
}

function toIsoString(localString?: string): string | null {
  if (!localString) return null;
  const d = new Date(localString);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

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
  } = useTypeEditorState<GearUsageData>({
    initialData: { items: gearUsageItems(data) },
    onSave,
    createMode,
    onChange,
  });

  const items = editData.items ?? [];
  const editable = isEditing || createMode;
  const gearName = (gearItemId: string) =>
    gearItems?.find((g: GearItem) => g.id === gearItemId)?.name ??
    'Unknown gear item';
  const unlistedGear =
    gearItems?.filter(
      (g: GearItem) => !items.some(item => item.gear_item_id === g.id)
    ) ?? [];

  const addItem = (gearItemId: string) =>
    setEditData(prev => ({
      items: [...(prev.items ?? []), { gear_item_id: gearItemId }],
    }));

  const removeItem = (gearItemId: string) =>
    setEditData(prev => ({
      items: (prev.items ?? []).filter(i => i.gear_item_id !== gearItemId),
    }));

  const setItemDate = (
    gearItemId: string,
    field: ItemDateField,
    value: string
  ) =>
    setEditData(prev => ({
      items: (prev.items ?? []).map(item =>
        item.gear_item_id === gearItemId
          ? { ...item, [field]: toIsoString(value) }
          : item
      ),
    }));

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
      await invalidateAfterMutation(queryClient, { queryKey: ['gear-items'] });
      addItem(newItem.id);
      setCreateDialogOpen(false);
      setNewGearItemName('');
      toast.success('Gear item created');
    } catch {
      toast.error('Failed to create gear item');
    } finally {
      setIsCreatingGearItem(false);
    }
  };

  const itemWindow = (item: GearUsageItem) => {
    if (!snipeItConnected) return null;
    const checkout = safeFormatDate(item.checkout_date);
    const checkin = safeFormatDate(item.checkin_date);
    if (!checkout && !checkin) return null;
    return `${checkout ?? 'Journal start'} – ${checkin ?? 'Journal end'}`;
  };

  const summaryItems = compactSummaryItems(
    items.length > 0
      ? {
          label: 'Gear Used',
          fullWidth: true,
          value: (
            <ul className='space-y-1' data-testid='gear-usage-items'>
              {items.map(item => (
                <li key={item.gear_item_id} data-testid='gear-usage-item'>
                  <span>{gearName(item.gear_item_id)}</span>
                  {itemWindow(item) && (
                    <span className='text-muted-foreground ml-2 font-normal'>
                      {itemWindow(item)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ),
        }
      : null
  );

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
        gridClassName='space-y-4'
        onEdit={handleEdit}
        onSave={async () => {
          const error = gearUsageItemsError(items);
          if (error) {
            toast.error(error);
            return;
          }
          await handleSave();
        }}
        onCancel={handleCancel}
      >
        <ul className='space-y-3' aria-label='Gear used'>
          {items.map(item => {
            const name = gearName(item.gear_item_id);
            const rowId = `${baseId}-${item.gear_item_id}`;
            return (
              <li
                key={item.gear_item_id}
                className='space-y-3 rounded-md border p-3'
                data-testid='gear-usage-item-row'
              >
                <div className='flex items-center justify-between gap-2'>
                  <span className='flex items-center gap-2 text-sm font-medium'>
                    <Wrench
                      className='text-muted-foreground h-4 w-4'
                      aria-hidden='true'
                    />
                    {name}
                  </span>
                  <Button
                    type='button'
                    variant='ghost'
                    size='icon'
                    aria-label={`Remove ${name}`}
                    data-testid='remove-gear-item'
                    disabled={!editable}
                    onClick={() => removeItem(item.gear_item_id)}
                  >
                    <X className='h-4 w-4' aria-hidden='true' />
                  </Button>
                </div>
                {snipeItConnected && (
                  <div className='grid gap-4 sm:grid-cols-2'>
                    <div className='space-y-2'>
                      <Label htmlFor={`${rowId}-checkout`}>
                        Checkout Date (Buffer)
                      </Label>
                      <Input
                        id={`${rowId}-checkout`}
                        data-testid='checkout-date-input'
                        type='datetime-local'
                        value={formatForInput(item.checkout_date)}
                        onChange={e =>
                          setItemDate(
                            item.gear_item_id,
                            'checkout_date',
                            e.target.value
                          )
                        }
                        disabled={!editable}
                      />
                    </div>
                    <div className='space-y-2'>
                      <Label htmlFor={`${rowId}-checkin`}>
                        Checkin Date (Buffer)
                      </Label>
                      <Input
                        id={`${rowId}-checkin`}
                        data-testid='checkin-date-input'
                        type='datetime-local'
                        value={formatForInput(item.checkin_date)}
                        onChange={e =>
                          setItemDate(
                            item.gear_item_id,
                            'checkin_date',
                            e.target.value
                          )
                        }
                        disabled={!editable}
                      />
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>

        <div className='flex flex-col space-y-2'>
          <Label htmlFor={`${baseId}-add-gear-item`}>Add Gear Item</Label>
          <Popover
            open={openCombobox && editable}
            onOpenChange={setOpenCombobox}
          >
            <PopoverTrigger asChild>
              <Button
                id={`${baseId}-add-gear-item`}
                variant='outline'
                role='combobox'
                aria-expanded={openCombobox && editable}
                disabled={!editable}
                className='w-full justify-between'
                data-testid='gear-item-selector'
              >
                Select gear item...
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
                    {unlistedGear.map((gear: GearItem) => (
                      <CommandItem
                        key={gear.id}
                        value={gear.name}
                        onSelect={() => {
                          addItem(gear.id);
                          setOpenCombobox(false);
                        }}
                      >
                        {gear.name}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
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
