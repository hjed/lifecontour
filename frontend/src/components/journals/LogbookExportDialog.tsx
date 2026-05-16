/**
 * LogbookExportDialog - Export outdoor logbook as PDF with optional filters.
 *
 * Provides a dialog with date range picker and activity type multi-select
 * for filtering the logbook export. Handles loading and error states.
 */

'use client';

import { useState } from 'react';
import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import { Calendar as CalendarIcon, Download, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import {
  useExportOutdoorLogbook,
  LogbookExportFilters,
} from '@/lib/api/journals';
import type { DateRange } from 'react-day-picker';

interface LogbookExportDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
}

// Outdoor activity types that are eligible for logbook export
const OUTDOOR_ACTIVITY_TYPES: { value: string; label: string }[] = [
  { value: 'BUSHWALKING', label: 'Bushwalking' },
  { value: 'CANYONING', label: 'Canyoning' },
  { value: 'CAVING', label: 'Caving' },
  { value: 'CLIMBING', label: 'Climbing' },
  { value: 'ABSEILING_TRIP', label: 'Abseiling Trip' },
  { value: 'KAYAKING', label: 'Kayaking' },
  { value: 'CANOEING', label: 'Canoeing' },
  { value: 'CROSS_COUNTRY_SKIING', label: 'Cross-Country Skiing' },
  { value: 'DOWNHILL_SKIING', label: 'Downhill Skiing' },
  { value: 'SNORKELLING', label: 'Snorkelling' },
  { value: 'DIVING', label: 'Diving' },
  { value: 'OUTDOOR_TRAINING', label: 'Outdoor Training' },
  { value: 'GEAR_MAINTENANCE', label: 'Gear Maintenance' },
];

export function LogbookExportDialog({
  open,
  onOpenChange,
}: LogbookExportDialogProps) {
  const [dateRange, setDateRange] = useState<DateRange | undefined>();
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);

  const exportMutation = useExportOutdoorLogbook();

  const handleTypeToggle = (type: string) => {
    setSelectedTypes(prev =>
      prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
    );
  };

  const handleExport = () => {
    const filters: LogbookExportFilters = {};

    if (dateRange?.from) {
      filters.start_date = format(dateRange.from, "yyyy-MM-dd'T'00:00:00XXX");
    }
    if (dateRange?.to) {
      filters.end_date = format(dateRange.to, "yyyy-MM-dd'T'23:59:59XXX");
    }
    if (selectedTypes.length > 0) {
      filters.activity_types = selectedTypes;
    }

    exportMutation.mutate(filters, {
      onSuccess: () => {
        onOpenChange(false);
        // Reset filters for next use
        setDateRange(undefined);
        setSelectedTypes([]);
      },
    });
  };

  const handleClearFilters = () => {
    setDateRange(undefined);
    setSelectedTypes([]);
  };

  // Format date range for display
  const getDateRangeDisplay = () => {
    if (!dateRange?.from) {
      return <span>All dates</span>;
    }

    if (dateRange.to) {
      return (
        <>
          {format(dateRange.from, 'dd MMM yyyy', { locale: enAU })} –{' '}
          {format(dateRange.to, 'dd MMM yyyy', { locale: enAU })}
        </>
      );
    }

    return format(dateRange.from, 'dd MMM yyyy', { locale: enAU });
  };

  const hasFilters = dateRange?.from !== undefined || selectedTypes.length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className='sm:max-w-[480px]'
        data-testid='logbook-export-dialog'
      >
        <DialogHeader>
          <DialogTitle>Export Outdoor Logbook</DialogTitle>
          <DialogDescription>
            Generate a PDF logbook of your outdoor activities. Optionally filter
            by date range and activity types.
          </DialogDescription>
        </DialogHeader>

        <div className='space-y-6 py-4'>
          {/* Date Range Filter */}
          <div className='space-y-2'>
            <Label>Date Range</Label>
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant='outline'
                  className={cn(
                    'w-full justify-start text-left font-normal',
                    !dateRange && 'text-muted-foreground'
                  )}
                  data-testid='export-date-range-trigger'
                >
                  <CalendarIcon className='mr-2 h-4 w-4' />
                  {getDateRangeDisplay()}
                </Button>
              </PopoverTrigger>
              <PopoverContent className='w-auto p-0' align='start'>
                <Calendar
                  mode='range'
                  selected={dateRange}
                  onSelect={setDateRange}
                  numberOfMonths={2}
                  locale={enAU}
                  data-testid='export-date-calendar'
                />
              </PopoverContent>
            </Popover>
          </div>

          {/* Activity Type Multi-select */}
          <div className='space-y-2'>
            <Label>Activity Types</Label>
            <p className='text-muted-foreground text-xs'>
              Leave empty to include all outdoor activities
            </p>
            <div
              className='max-h-48 space-y-2 overflow-y-auto rounded-md border p-3'
              role='group'
              aria-label='Activity type filters'
            >
              {OUTDOOR_ACTIVITY_TYPES.map(type => (
                <div key={type.value} className='flex items-center space-x-2'>
                  <Checkbox
                    id={`export-type-${type.value}`}
                    checked={selectedTypes.includes(type.value)}
                    onCheckedChange={() => handleTypeToggle(type.value)}
                    data-testid={`export-type-${type.value}`}
                  />
                  <label
                    htmlFor={`export-type-${type.value}`}
                    className='text-sm leading-none font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-70'
                  >
                    {type.label}
                  </label>
                </div>
              ))}
            </div>
          </div>

          {/* Clear Filters */}
          {hasFilters && (
            <Button
              variant='ghost'
              size='sm'
              onClick={handleClearFilters}
              className='w-full'
              data-testid='export-clear-filters'
            >
              Clear Filters
            </Button>
          )}
        </div>

        <DialogFooter>
          <Button
            variant='outline'
            onClick={() => onOpenChange(false)}
            disabled={exportMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            onClick={handleExport}
            disabled={exportMutation.isPending}
            data-testid='export-submit'
          >
            {exportMutation.isPending ? (
              <>
                <Loader2 className='mr-2 h-4 w-4 animate-spin' />
                Generating PDF…
              </>
            ) : (
              <>
                <Download className='mr-2 h-4 w-4' />
                Export PDF
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
