/**
 * JournalTypeManager component allows adding or removing types from an existing journal.
 */

'use client';

import { useState } from 'react';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from '@/components/ui/hover-card';
import { JournalType } from '@/types/journals';
import { TYPE_ICONS, TYPE_LABELS } from './JournalTypeBadges';
import { cn } from '@/lib/utils';

interface JournalTypeManagerProps {
  readonly currentTypes: JournalType[];
  readonly onTypeAdd: (type: JournalType) => Promise<void>;
  readonly onTypeRemove: (type: JournalType) => Promise<void>;
  readonly className?: string;
}

// These are parent types that get added automatically when children are added,
// or that people usually don't add directly when a more specific child is available,
// but they CAN add them directly if they just want a generic 'Fitness' entry.
// For the UI, we just list all available JournalType enums that aren't already present.
const ALL_TYPES = Object.values(JournalType);

export function JournalTypeManager({
  currentTypes,
  onTypeAdd,
  onTypeRemove,
  className,
}: JournalTypeManagerProps) {
  const [isAdding, setIsAdding] = useState(false);
  const [isRemovingType, setIsRemovingType] = useState<string | null>(null);

  const availableTypes = ALL_TYPES.filter(
    type => !currentTypes.includes(type)
  ).sort((a, b) => TYPE_LABELS[a].localeCompare(TYPE_LABELS[b]));

  const handleAdd = async (type: JournalType) => {
    try {
      setIsAdding(true);
      await onTypeAdd(type);
    } catch (error) {
      console.error('Failed to add type:', error);
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemove = async (type: JournalType) => {
    if (
      !confirm(
        `Are you sure you want to remove the ${TYPE_LABELS[type]} type and all its data?`
      )
    ) {
      return;
    }

    try {
      setIsRemovingType(type);
      await onTypeRemove(type);
    } catch (error) {
      console.error('Failed to remove type:', error);
    } finally {
      setIsRemovingType(null);
    }
  };

  return (
    <div
      className={cn('flex flex-wrap items-center gap-2', className)}
      data-testid='journal-type-manager'
    >
      {currentTypes.map(type => {
        const Icon = TYPE_ICONS[type];
        const label = TYPE_LABELS[type];

        return (
          <HoverCard key={type}>
            <HoverCardTrigger asChild>
              <Button
                variant='outline'
                size='sm'
                className='h-7 gap-1.5 rounded-full px-3 text-xs'
                data-testid={`manage-type-${type}`}
                disabled={isRemovingType === type}
                aria-label={`Manage ${label} type`}
              >
                {Icon && <Icon className='h-3.5 w-3.5' />}
                {label}
              </Button>
            </HoverCardTrigger>
            <HoverCardContent className='w-auto p-2'>
              <div className='flex flex-col gap-2'>
                <span className='text-sm font-medium'>Manage {label}</span>
                <span className='text-muted-foreground text-xs'>
                  Manage this journal type.
                </span>
                <Button
                  variant='destructive'
                  size='sm'
                  onClick={() => handleRemove(type)}
                  disabled={isRemovingType === type}
                  className='mt-2 w-full'
                  data-testid={`remove-type-${type}`}
                >
                  Remove Type
                </Button>
              </div>
            </HoverCardContent>
          </HoverCard>
        );
      })}

      {availableTypes.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant='ghost'
              size='sm'
              className='text-muted-foreground hover:text-foreground h-7 gap-1.5 rounded-full border border-dashed px-3 text-xs'
              data-testid='add-type-button'
              aria-label='Add journal type'
              disabled={isAdding}
            >
              <Plus className='h-3.5 w-3.5' />
              Add Type
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align='start'
            className='h-[300px] w-[200px] overflow-y-auto'
          >
            {availableTypes.map(type => {
              const Icon = TYPE_ICONS[type];
              const label = TYPE_LABELS[type];
              return (
                <DropdownMenuItem
                  key={type}
                  onClick={() => handleAdd(type)}
                  className='cursor-pointer gap-2'
                  data-testid={`add-type-option-${type}`}
                >
                  {Icon && <Icon className='text-muted-foreground h-4 w-4' />}
                  {label}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}
