'use client';

import { useState, useId } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Wrench, Plus, Check, ChevronsUpDown } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';

import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
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

import type { GearMaintenanceData } from '@/types/journals';
import type { GearItem } from '@/types/gearItems';
import { getGearItems, createGearItem } from '@/lib/api/gearItems';
import {
  compactSummaryItems,
  GenericTypeEditorLayout,
} from './GenericTypeEditorLayout';
import { useTypeEditorState } from './useTypeEditorState';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { invalidateAfterMutation } from '@/lib/api/invalidate-after-mutation';

interface GearMaintenanceTypeEditorProps {
  readonly journalId?: string;
  readonly data?: GearMaintenanceData;
  readonly onSave?: (data: GearMaintenanceData) => Promise<void>;
  readonly className?: string;
  readonly 'data-testid'?: string;
  readonly createMode?: boolean;
  readonly onChange?: (data: GearMaintenanceData) => void;
}

const DEFAULT_DATA: GearMaintenanceData = {};

// Mirrors the backend MaintenanceType enum. The last five match Snipe-IT's
// maintenance kinds one-to-one, so an imported record keeps its kind.
const MAINTENANCE_TYPES = [
  'routine inspection',
  'routine maintenance',
  'repairing gear',
  'retiring gear',
  'upgrading gear',
  'calibration',
  'software support',
  'hardware support',
  'configuration change',
] as const;

export function GearMaintenanceTypeEditor({
  journalId: _journalId,
  data,
  onSave,
  className,
  'data-testid': testId,
  createMode = false,
  onChange,
}: GearMaintenanceTypeEditorProps) {
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
      await invalidateAfterMutation(queryClient, { queryKey: ['gear-items'] });
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

  const summaryItems = compactSummaryItems(
    selectedGearItem
      ? {
          label: 'Gear Item',
          value: selectedGearItem.name,
        }
      : null,
    editData?.maintenance_type
      ? {
          label: 'Maintenance Type',
          value: editData.maintenance_type,
        }
      : null,
    editData?.retirement_reason
      ? {
          label: 'Retirement Reason',
          value: editData.retirement_reason,
        }
      : null,
    editData?.activity_types && editData.activity_types.length > 0
      ? {
          label: 'Activity Types',
          value: editData.activity_types.join(', '),
        }
      : null
  );

  return (
    <>
      <GenericTypeEditorLayout
        className={className}
        testId={testId || 'gear-maintenance-type-editor'}
        createMode={createMode}
        isEditing={isEditing}
        emptyMessage='No gear maintenance details provided.'
        summaryItems={summaryItems}
        summaryTestId='gear-maintenance-summary'
        onEdit={handleEdit}
        onSave={handleSave}
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
                  aria-expanded={openCombobox}
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
                              gear_item_id:
                                item.id === editData.gear_item_id
                                  ? null
                                  : item.id,
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

          <div className='grid gap-4 sm:grid-cols-2'>
            <div className='space-y-2'>
              <Label htmlFor={`${baseId}-maintenance-type`}>
                Maintenance Type
              </Label>
              <Select
                value={editData.maintenance_type ?? ''}
                onValueChange={value =>
                  setEditData(prev => ({
                    ...prev,
                    maintenance_type: value,
                    retirement_reason:
                      value === 'retiring gear' ? prev.retirement_reason : null,
                  }))
                }
                disabled={!isEditing && !createMode}
              >
                <SelectTrigger
                  id={`${baseId}-maintenance-type`}
                  data-testid='maintenance-type-selector'
                >
                  <SelectValue placeholder='Select type...' />
                </SelectTrigger>
                <SelectContent>
                  {MAINTENANCE_TYPES.map(type => (
                    <SelectItem key={type} value={type}>
                      {type}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {editData.maintenance_type === 'retiring gear' && (
              <div className='space-y-2'>
                <Label htmlFor={`${baseId}-retirement-reason`}>
                  Retirement Reason
                </Label>
                <Input
                  id={`${baseId}-retirement-reason`}
                  data-testid='retirement-reason-input'
                  value={editData.retirement_reason ?? ''}
                  onChange={e =>
                    setEditData(prev => ({
                      ...prev,
                      retirement_reason: e.target.value || null,
                    }))
                  }
                  disabled={!isEditing && !createMode}
                  placeholder='e.g. Too much wear and tear'
                />
              </div>
            )}
          </div>

          <div className='space-y-2'>
            <Label className='mb-2 flex items-center gap-2'>
              Activity Types
            </Label>
            <div className='grid grid-cols-2 gap-3 sm:grid-cols-3'>
              {[
                { value: 'abseiling_trip', label: 'Abseiling' },
                { value: 'bushwalking', label: 'Bushwalking' },
                { value: 'canoeing', label: 'Canoeing' },
                { value: 'canyoning', label: 'Canyoning' },
                { value: 'caving', label: 'Caving' },
                { value: 'climbing', label: 'Climbing' },
                {
                  value: 'cross_country_skiing',
                  label: 'Cross-Country Skiing',
                },
                { value: 'diving', label: 'Diving' },
                { value: 'downhill_skiing', label: 'Downhill Skiing' },
                { value: 'kayaking', label: 'Kayaking' },
                { value: 'outdoor_training', label: 'Outdoor Training' },
                { value: 'snorkelling', label: 'Snorkelling' },
              ].map(subtype => {
                const isChecked =
                  editData.activity_types?.includes(subtype.value) ?? false;
                return (
                  <div
                    key={subtype.value}
                    className='flex items-center space-x-2'
                  >
                    <Checkbox
                      id={`${baseId}-${subtype.value}`}
                      checked={isChecked}
                      disabled={!isEditing && !createMode}
                      onCheckedChange={checked => {
                        const current = editData.activity_types ?? [];
                        let next;
                        if (checked === true) {
                          next = [...current, subtype.value];
                        } else {
                          next = current.filter(v => v !== subtype.value);
                        }
                        setEditData(prev => ({
                          ...prev,
                          activity_types: next.length > 0 ? next : null,
                        }));
                      }}
                      data-testid={`activity-type-${subtype.value}`}
                    />
                    <Label
                      htmlFor={`${baseId}-${subtype.value}`}
                      className='text-sm leading-none font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-70'
                    >
                      {subtype.label}
                    </Label>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </GenericTypeEditorLayout>

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Gear Item</DialogTitle>
            <DialogDescription>
              Add a new gear item to your inventory to log maintenance.
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
