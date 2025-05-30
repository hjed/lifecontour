# Localization Patterns - Australian English

This document provides implementation examples for Australian English localization.

## Date and Time Formatting

```typescript
// utils/dateFormat.ts
import { format, parseISO } from 'date-fns';
import { enAU } from 'date-fns/locale';

export function formatAustralianDate(date: string | Date): string {
  const dateObj = typeof date === 'string' ? parseISO(date) : date;
  return format(dateObj, 'dd/MM/yyyy', { locale: enAU }); // DD/MM/YYYY
}

export function formatAustralianDateTime(date: string | Date): string {
  const dateObj = typeof date === 'string' ? parseISO(date) : date;
  return format(dateObj, 'dd/MM/yyyy h:mm a', { locale: enAU }); // DD/MM/YYYY 2:30 PM
}

export function formatAustralianTime(date: string | Date): string {
  const dateObj = typeof date === 'string' ? parseISO(date) : date;
  return format(dateObj, 'h:mm a', { locale: enAU }); // 2:30 PM
}

// Usage in components
export function ContactCreatedDate({ createdAt }: { createdAt: string }) {
  return (
    <time dateTime={createdAt} className="text-sm text-muted-foreground">
      Created on {formatAustralianDate(createdAt)}
    </time>
  );
}
```

## React Intl Configuration

```typescript
// lib/i18n.ts
import { createIntl, createIntlCache } from 'react-intl';

// Australian English messages
const messages = {
  'contact.create.title': 'Create Contact',
  'contact.edit.title': 'Edit Contact',
  'contact.delete.confirm': 'Are you sure you want to delete this contact?',
  'contact.tags.label': 'Tags',
  'contact.email.label': 'Email Address',
  'contact.phone.label': 'Phone Number',
  'contact.company.label': 'Organisation', // Australian spelling
  'contact.notes.label': 'Notes',
  'date.created': 'Created on {date}',
  'date.updated': 'Last updated on {date}',
  'sync.status.syncing': 'Synchronising...', // Australian spelling
  'sync.status.complete': 'Synchronisation complete',
  'colour.picker.label': 'Choose Colour', // Australian spelling
  'settings.preferences': 'Preferences',
  'action.delete': 'Move to Bin', // Australian terminology
  'phone.mobile': 'Mobile', // Not "cell phone"
  'address.postcode': 'Postcode', // Not "zip code"
};

const cache = createIntlCache();
export const intl = createIntl({
  locale: 'en-AU',
  messages,
}, cache);

// React component wrapper
export function IntlProvider({ children }: { children: React.ReactNode }) {
  return (
    <ReactIntlProvider locale="en-AU" messages={messages}>
      {children}
    </ReactIntlProvider>
  );
}
```

## Australian Terminology Constants

```typescript
// constants/terminology.ts
export const AUSTRALIAN_TERMS = {
  // Spelling differences
  colour: 'colour', // not 'color'
  centre: 'centre', // not 'center'
  realise: 'realise', // not 'realize'
  organise: 'organise', // not 'organize'
  synchronise: 'synchronise', // not 'synchronize'
  analyse: 'analyse', // not 'analyze'
  recognise: 'recognise', // not 'recognize'

  // Business terms
  company: 'organisation', // or 'company'
  mobile: 'mobile', // not 'cell phone'
  postcode: 'postcode', // not 'zip code'
  
  // UI terms
  trash: 'bin', // delete icon
  settings: 'preferences', // or 'settings'
  favorites: 'favourites',
  
  // Date/time
  timezone: 'time zone',
} as const;

// Usage in components
export function DeleteButton({ onDelete }: { onDelete: () => void }) {
  return (
    <Button variant="destructive" onClick={onDelete}>
      <Trash2 className="h-4 w-4" />
      Move to {AUSTRALIAN_TERMS.trash}
    </Button>
  );
}
```

## Currency and Number Formatting

```typescript
// utils/currency.ts
export function formatAustralianCurrency(amount: number): string {
  return new Intl.NumberFormat('en-AU', {
    style: 'currency',
    currency: 'AUD',
  }).format(amount);
}

export function formatAustralianNumber(value: number): string {
  return new Intl.NumberFormat('en-AU').format(value);
}

export function formatAustralianPercentage(value: number): string {
  return new Intl.NumberFormat('en-AU', {
    style: 'percent',
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value);
}

// Usage examples:
// formatAustralianCurrency(1234.56) → "$1,234.56"
// formatAustralianNumber(1234567) → "1,234,567"
// formatAustralianPercentage(0.1234) → "12.3%"
```

## Phone Number Formatting

```typescript
// utils/phoneFormat.ts
export function formatAustralianPhone(phone: string): string {
  // Remove all non-digits
  const digits = phone.replace(/\D/g, '');
  
  // Australian mobile format: 04XX XXX XXX
  if (digits.startsWith('04') && digits.length === 10) {
    return `${digits.slice(0, 4)} ${digits.slice(4, 7)} ${digits.slice(7)}`;
  }
  
  // Australian landline format: (0X) XXXX XXXX
  if (digits.startsWith('0') && digits.length === 10) {
    return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)} ${digits.slice(6)}`;
  }
  
  // International format: +61 X XXXX XXXX
  if (digits.startsWith('61') && digits.length === 11) {
    return `+61 ${digits.slice(2, 3)} ${digits.slice(3, 7)} ${digits.slice(7)}`;
  }
  
  return phone; // Return original if no pattern matches
}

export function validateAustralianPhone(phone: string): boolean {
  const digits = phone.replace(/\D/g, '');
  
  // Australian mobile: starts with 04, 10 digits total
  if (digits.startsWith('04') && digits.length === 10) {
    return true;
  }
  
  // Australian landline: starts with 0, 10 digits total, second digit 2-8
  if (digits.startsWith('0') && digits.length === 10) {
    const areaCode = digits.slice(1, 2);
    return ['2', '3', '4', '7', '8'].includes(areaCode);
  }
  
  return false;
}
```

## Address Formatting

```typescript
// utils/addressFormat.ts
interface AustralianAddress {
  streetNumber?: string;
  streetName?: string;
  streetType?: string; // Street, Road, Avenue, etc.
  suburb: string;
  state: string;
  postcode: string;
  country?: string;
}

export function formatAustralianAddress(address: AustralianAddress): string {
  const parts: string[] = [];
  
  // Street address
  if (address.streetNumber && address.streetName) {
    const street = [
      address.streetNumber,
      address.streetName,
      address.streetType
    ].filter(Boolean).join(' ');
    parts.push(street);
  }
  
  // Suburb, State, Postcode
  const location = `${address.suburb} ${address.state} ${address.postcode}`;
  parts.push(location);
  
  // Country (if not Australia)
  if (address.country && address.country !== 'Australia') {
    parts.push(address.country);
  }
  
  return parts.join('\n');
}

export const AUSTRALIAN_STATES = [
  { code: 'NSW', name: 'New South Wales' },
  { code: 'VIC', name: 'Victoria' },
  { code: 'QLD', name: 'Queensland' },
  { code: 'WA', name: 'Western Australia' },
  { code: 'SA', name: 'South Australia' },
  { code: 'TAS', name: 'Tasmania' },
  { code: 'ACT', name: 'Australian Capital Territory' },
  { code: 'NT', name: 'Northern Territory' },
] as const;
```

## Form Validation Messages

```typescript
// utils/validationMessages.ts
export const AUSTRALIAN_VALIDATION_MESSAGES = {
  required: 'This field is required',
  email: 'Please enter a valid email address',
  phone: 'Please enter a valid Australian phone number (e.g., 0400 123 456)',
  postcode: 'Please enter a valid Australian postcode (4 digits)',
  
  // Australian-specific validations
  abn: 'Please enter a valid Australian Business Number (ABN)',
  tfn: 'Please enter a valid Tax File Number (TFN)',
  medicare: 'Please enter a valid Medicare number',
  
  // Date validations with Australian format
  date: 'Please enter a valid date (DD/MM/YYYY)',
  dateRange: 'End date must be after start date',
  
  // Business validations
  organisationName: 'Please enter a valid organisation name',
  
  // Character limits with Australian spelling
  maxLength: (max: number) => `Maximum ${max} characters allowed`,
  minLength: (min: number) => `Minimum ${min} characters required`,
} as const;
```

## Component Examples with Australian Localization

```typescript
// components/AustralianDatePicker.tsx
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { CalendarIcon } from 'lucide-react';
import { formatAustralianDate } from '@/utils/dateFormat';

interface AustralianDatePickerProps {
  value?: Date;
  onChange: (date: Date | undefined) => void;
  placeholder?: string;
}

export function AustralianDatePicker({ 
  value, 
  onChange, 
  placeholder = "Select date" 
}: AustralianDatePickerProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className="w-full justify-start text-left font-normal"
        >
          <CalendarIcon className="mr-2 h-4 w-4" />
          {value ? formatAustralianDate(value) : placeholder}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          selected={value}
          onSelect={onChange}
          locale={enAU}
          initialFocus
        />
      </PopoverContent>
    </Popover>
  );
}
```
