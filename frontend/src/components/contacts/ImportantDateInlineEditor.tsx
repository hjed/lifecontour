'use client';

import { useState } from 'react';
import { Check, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  ImportantDateAttributes,
  ImportantDatePrecision,
  ImportantDateTypeEnum,
} from '@/types/contacts';
import {
  useCreateCustomDateType,
  useCustomDateTypes,
} from '@/lib/api/contacts';

export interface ImportantDateInlineEditorProps {
  initialData?: ImportantDateAttributes;
  onSave: (data: ImportantDateAttributes) => Promise<void>;
  onCancel: () => void;
  isLoading?: boolean;
}

export function ImportantDateInlineEditor({
  initialData,
  onSave,
  onCancel,
  isLoading = false,
}: ImportantDateInlineEditorProps) {
  const [isSaving, setIsSaving] = useState(false);
  const [dateType, setDateType] = useState<ImportantDateTypeEnum | string>(
    initialData?.date_type || ImportantDateTypeEnum.BIRTHDAY
  );
  const [precision, setPrecision] = useState<ImportantDatePrecision | string>(
    initialData?.precision || ImportantDatePrecision.FULL
  );

  const [year, setYear] = useState<string>(initialData?.year?.toString() || '');
  const [month, setMonth] = useState<string>(
    initialData?.month?.toString() || ''
  );
  const [day, setDay] = useState<string>(initialData?.day?.toString() || '');

  // For custom string type, if API supports string instead of enum.
  const [customType, setCustomType] = useState<string>(
    initialData?.date_type === ImportantDateTypeEnum.CUSTOM &&
      initialData?.custom_date_type_name
      ? initialData.custom_date_type_name
      : ''
  );

  const { data: customDateTypesData } = useCustomDateTypes();
  const createCustomMutation = useCreateCustomDateType();

  const handleSave = async () => {
    // Basic validation
    if (precision === ImportantDatePrecision.FULL && (!year || !month || !day))
      return;
    if (precision === ImportantDatePrecision.DAY_MONTH && (!month || !day))
      return;
    if (precision === ImportantDatePrecision.YEAR && !year) return;

    if (dateType === ImportantDateTypeEnum.CUSTOM && !customType.trim()) return;

    const parsedYear =
      precision === ImportantDatePrecision.FULL ||
      precision === ImportantDatePrecision.YEAR
        ? year
          ? parseInt(year, 10)
          : null
        : null;

    const parsedMonth =
      precision === ImportantDatePrecision.FULL ||
      precision === ImportantDatePrecision.DAY_MONTH
        ? month
          ? parseInt(month, 10)
          : null
        : null;

    const parsedDay =
      precision === ImportantDatePrecision.FULL ||
      precision === ImportantDatePrecision.DAY_MONTH
        ? day
          ? parseInt(day, 10)
          : null
        : null;

    // Validate parsed numbers are not NaN (can happen with non-numeric browser input)
    if (parsedYear !== null && isNaN(parsedYear)) return;
    if (parsedMonth !== null && isNaN(parsedMonth)) return;
    if (parsedDay !== null && isNaN(parsedDay)) return;

    let customDateTypeId: number | null = null;
    let customDateTypeName: string | null = null;

    if (dateType === ImportantDateTypeEnum.CUSTOM) {
      const existingTypes = customDateTypesData?.data || [];
      const trimmedName = customType.trim();
      const existing = existingTypes.find(
        t => t.attributes.name.toLowerCase() === trimmedName.toLowerCase()
      );

      if (existing) {
        customDateTypeId = parseInt(existing.id, 10);
        customDateTypeName = existing.attributes.name;
      } else {
        const newType = await createCustomMutation.mutateAsync(trimmedName);
        customDateTypeId = parseInt(newType.data.id, 10);
        customDateTypeName = newType.data.attributes.name;
      }
    }

    const data: ImportantDateAttributes = {
      date_type: dateType,
      precision,
      year: parsedYear,
      month: parsedMonth,
      day: parsedDay,
      ...(customDateTypeId ? { custom_date_type_id: customDateTypeId } : {}),
      ...(customDateTypeName
        ? { custom_date_type_name: customDateTypeName }
        : {}),
    };

    setIsSaving(true);
    try {
      await onSave(data);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className='bg-muted/20 flex flex-wrap items-center gap-2 rounded-md border p-2'>
      <Select value={dateType} onValueChange={setDateType} disabled={isLoading}>
        <SelectTrigger
          className='h-8 w-[140px] text-xs'
          aria-label='Important Date Type'
        >
          <SelectValue placeholder='Type' />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ImportantDateTypeEnum.BIRTHDAY}>
            Birthday
          </SelectItem>
          <SelectItem value={ImportantDateTypeEnum.ANNIVERSARY_MARRIAGE}>
            Marriage Ann.
          </SelectItem>
          <SelectItem value={ImportantDateTypeEnum.ANNIVERSARY_WORK}>
            Work Ann.
          </SelectItem>
          <SelectItem value={ImportantDateTypeEnum.FIRST_MET}>
            First Met
          </SelectItem>
          <SelectItem value={ImportantDateTypeEnum.CUSTOM}>
            Custom...
          </SelectItem>
        </SelectContent>
      </Select>

      {dateType === ImportantDateTypeEnum.CUSTOM && (
        <Input
          value={customType}
          onChange={e => setCustomType(e.target.value)}
          placeholder='Custom name'
          className='h-8 w-[100px] text-xs'
          disabled={isLoading}
        />
      )}

      <Select
        value={precision}
        onValueChange={setPrecision}
        disabled={isLoading}
      >
        <SelectTrigger
          className='h-8 w-[110px] text-xs'
          aria-label='Important Date Precision'
        >
          <SelectValue placeholder='Precision' />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ImportantDatePrecision.FULL}>Full Date</SelectItem>
          <SelectItem value={ImportantDatePrecision.DAY_MONTH}>
            Day & Month
          </SelectItem>
          <SelectItem value={ImportantDatePrecision.YEAR}>Year Only</SelectItem>
        </SelectContent>
      </Select>

      {/* Date inputs depending on precision */}
      {(precision === ImportantDatePrecision.FULL ||
        precision === ImportantDatePrecision.DAY_MONTH) && (
        <>
          <Input
            type='number'
            placeholder='DD'
            value={day}
            onChange={e => setDay(e.target.value)}
            className='h-8 w-[60px] text-xs'
            min={1}
            max={31}
            disabled={isLoading}
          />
          <Input
            type='number'
            placeholder='MM'
            value={month}
            onChange={e => setMonth(e.target.value)}
            className='h-8 w-[60px] text-xs'
            min={1}
            max={12}
            disabled={isLoading}
          />
        </>
      )}

      {(precision === ImportantDatePrecision.FULL ||
        precision === ImportantDatePrecision.YEAR) && (
        <Input
          type='number'
          placeholder='YYYY'
          value={year}
          onChange={e => setYear(e.target.value)}
          className='h-8 w-[70px] text-xs'
          min={1900}
          max={2100}
          disabled={isLoading}
        />
      )}

      <div className='ml-auto flex gap-1'>
        <Button
          size='sm'
          variant='ghost'
          onClick={handleSave}
          disabled={isLoading || isSaving || createCustomMutation.isPending}
          className='h-8 w-8 p-0 text-green-600 hover:bg-green-50 hover:text-green-700'
          aria-label='Save date'
        >
          <Check className='h-4 w-4' />
        </Button>

        <Button
          size='sm'
          variant='ghost'
          onClick={onCancel}
          disabled={isLoading || isSaving || createCustomMutation.isPending}
          className='h-8 w-8 p-0 text-red-600 hover:bg-red-50 hover:text-red-700'
          aria-label='Cancel edit'
        >
          <X className='h-4 w-4' />
        </Button>
      </div>
    </div>
  );
}
