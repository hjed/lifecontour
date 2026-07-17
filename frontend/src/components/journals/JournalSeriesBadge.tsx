/**
 * JournalSeriesBadge component for displaying and managing series memberships.
 *
 * Shows series badges (linking to the series page) with inline add/remove and
 * create-new-series functionality. Series group related journals — recurring
 * calendar events are grouped automatically, and users can group journals
 * manually (e.g. a series of medical appointments).
 */

'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Layers, X, Plus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import type { JournalSeries, JournalSeriesRef } from '@/types/journals';

interface JournalSeriesBadgeProps {
  readonly series: JournalSeriesRef[];
  readonly onSeriesAdd?: (seriesId: string) => Promise<void>;
  readonly onSeriesRemove?: (seriesId: string) => Promise<void>;
  readonly onSeriesCreate?: (name: string) => Promise<void>;
  readonly availableSeries?: JournalSeries[];
  readonly disabled?: boolean;
  readonly className?: string;
}

/**
 * Series badge component with inline add/remove and create functionality.
 * Badges link to the series page listing all member journals.
 */
export function JournalSeriesBadge({
  series,
  onSeriesAdd,
  onSeriesRemove,
  onSeriesCreate,
  availableSeries = [],
  disabled = false,
  className,
}: JournalSeriesBadgeProps) {
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [selectedSeriesId, setSelectedSeriesId] = useState<string | null>(null);
  const [newSeriesName, setNewSeriesName] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleAddSeries = async () => {
    if (!onSeriesAdd || !selectedSeriesId) return;

    setIsLoading(true);
    try {
      await onSeriesAdd(selectedSeriesId);
      setIsAddOpen(false);
      setSelectedSeriesId(null);
    } catch (error) {
      console.error('Failed to add to series:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateSeries = async () => {
    if (!onSeriesCreate || !newSeriesName.trim()) return;

    setIsLoading(true);
    try {
      await onSeriesCreate(newSeriesName.trim());
      setIsAddOpen(false);
      setNewSeriesName('');
    } catch (error) {
      console.error('Failed to create series:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemoveSeries = async (seriesId: string) => {
    if (!onSeriesRemove) return;

    setIsLoading(true);
    try {
      await onSeriesRemove(seriesId);
    } catch (error) {
      console.error('Failed to remove from series:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Filter out series the journal is already a member of
  const unassignedSeries = availableSeries.filter(
    candidate => !series.some(existing => existing.id === candidate.id)
  );

  return (
    <div
      className={cn('flex flex-wrap items-center gap-2', className)}
      data-testid='series-badges'
    >
      {/* Existing Series Badges */}
      {series.map(item => (
        <Badge
          key={item.id}
          variant='outline'
          className='gap-1.5 pr-1 text-xs'
          data-testid={`series-badge-${item.id}`}
        >
          <Link
            href={`/journals/series/${item.id}`}
            className='flex items-center gap-1.5 hover:underline'
          >
            <Layers className='h-3 w-3' />
            <span>{item.name}</span>
          </Link>
          {onSeriesRemove && (
            <button
              type='button'
              onClick={() => handleRemoveSeries(item.id)}
              disabled={disabled || isLoading}
              className='hover:bg-muted ml-1 rounded-sm p-0.5 transition-colors'
              aria-label={`Remove from series ${item.name}`}
              data-testid={`remove-series-${item.id}`}
            >
              <X className='h-3 w-3' />
            </button>
          )}
        </Badge>
      ))}

      {/* Add to Series Button */}
      {!disabled && onSeriesAdd && (
        <Popover open={isAddOpen} onOpenChange={setIsAddOpen}>
          <PopoverTrigger asChild>
            <Button
              variant='outline'
              size='sm'
              className='h-6 gap-1 text-xs'
              disabled={disabled || isLoading}
              data-testid='add-series-button'
            >
              <Plus className='h-3 w-3' />
              Add to Series
            </Button>
          </PopoverTrigger>
          <PopoverContent className='w-64 p-3' align='start'>
            <div className='space-y-3'>
              {unassignedSeries.length > 0 && (
                <div className='space-y-2'>
                  <label
                    htmlFor='series-select'
                    className='text-sm font-medium'
                  >
                    Select Series
                  </label>
                  <Select
                    value={selectedSeriesId ?? undefined}
                    onValueChange={value => setSelectedSeriesId(value)}
                    disabled={isLoading}
                  >
                    <SelectTrigger
                      id='series-select'
                      data-testid='series-select'
                    >
                      <SelectValue placeholder='Choose a series' />
                    </SelectTrigger>
                    <SelectContent>
                      {unassignedSeries.map(item => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <Button
                    onClick={handleAddSeries}
                    disabled={!selectedSeriesId || isLoading}
                    className='w-full'
                    size='sm'
                  >
                    Add
                  </Button>
                </div>
              )}

              {onSeriesCreate && (
                <div className='space-y-2'>
                  <label
                    htmlFor='new-series-name'
                    className='text-sm font-medium'
                  >
                    Or create a new series
                  </label>
                  <Input
                    id='new-series-name'
                    value={newSeriesName}
                    onChange={e => setNewSeriesName(e.target.value)}
                    placeholder='New series name'
                    disabled={isLoading}
                    data-testid='new-series-name-input'
                  />
                  <Button
                    onClick={handleCreateSeries}
                    disabled={!newSeriesName.trim() || isLoading}
                    className='w-full'
                    size='sm'
                    variant='secondary'
                  >
                    Create &amp; Add
                  </Button>
                </div>
              )}
            </div>
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}
