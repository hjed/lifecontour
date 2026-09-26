/**
 * Specialized inline edit field for addresses.
 *
 * Provides structured address editing with multiple fields
 * and proper address formatting for display.
 */

'use client';

import { useState, useCallback, useRef, useEffect, useId } from 'react';
import { Check, X, MapPin } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export interface AddressData {
  street_line_1?: string;
  street_line_2?: string;
  locality?: string; // City
  region?: string; // State/Province
  postal_code?: string;
  country_code?: string;
}

export interface InlineEditAddressFieldProps {
  /** Current address value (formatted string or structured data) */
  readonly value: string | AddressData | null | undefined;
  /** Function to call when saving changes */
  readonly onSave: (value: AddressData) => Promise<void>;
  /** Placeholder text when value is empty */
  readonly placeholder?: string;
  /** Validation function that returns error message or null */
  readonly validation?: (value: AddressData) => string | null;
  /** Whether the field is disabled */
  readonly disabled?: boolean;
  /** Additional CSS classes */
  readonly className?: string;
  /** Test ID for testing */
  readonly 'data-testid'?: string;
  /** ARIA label for accessibility */
  readonly 'aria-label'?: string;
  /** Whether to show address icon */
  readonly showIcon?: boolean;
}

/**
 * Parse address string into structured data
 */
function parseAddressString(addressString: string): AddressData {
  // Simple parsing - in a real app, you might use a more sophisticated parser
  const lines = addressString
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean);

  if (lines.length === 0) {
    return {};
  }

  // Basic heuristic parsing
  const result: AddressData = {};

  if (lines.length >= 1) {
    result.street_line_1 = lines[0];
  }

  if (lines.length >= 2) {
    // If second line looks like a street address, use it as street_line_2
    // Otherwise, assume it's city/region/postal
    const secondLine = lines[1];
    if (secondLine.match(/^(apt|apartment|unit|suite|floor|#)/i)) {
      result.street_line_2 = secondLine;
      if (lines.length >= 3) {
        parseLocationLine(lines[2], result);
      }
    } else {
      parseLocationLine(secondLine, result);
    }
  }

  return result;
}

/**
 * Parse a location line (city, state, postal code)
 */
function parseLocationLine(line: string, result: AddressData) {
  // Regex pattern to match state/region followed by postal code
  // Matches: "State PostalCode" or "State 12345" or "NSW 2000"
  const STATE_POSTAL_PATTERN = /^(.+?)\s+([A-Z0-9\s-]+)$/;

  // Simple parsing for "City, State PostalCode" format
  const parts = line.split(',').map(p => p.trim());

  if (parts.length >= 1) {
    result.locality = parts[0];
  }

  if (parts.length >= 2) {
    const statePostal = parts[1].trim();
    const match = statePostal.match(STATE_POSTAL_PATTERN);
    if (match) {
      result.region = match[1].trim();
      result.postal_code = match[2].trim();
    } else {
      result.region = statePostal;
    }
  }
}

/**
 * Format address data for display
 */
export function formatAddressForDisplay(
  address: AddressData | string | null | undefined
): string {
  if (!address) return '';

  if (typeof address === 'string') {
    return address;
  }

  const parts: string[] = [];

  if (address.street_line_1) {
    parts.push(address.street_line_1);
  }

  if (address.street_line_2) {
    parts.push(address.street_line_2);
  }

  // Format city, state postal code line
  const locationParts: string[] = [];
  if (address.locality) {
    locationParts.push(address.locality);
  }

  if (address.region || address.postal_code) {
    const regionPostal = [address.region, address.postal_code]
      .filter(Boolean)
      .join(' ');
    if (regionPostal) {
      locationParts.push(regionPostal);
    }
  }

  if (locationParts.length > 0) {
    parts.push(locationParts.join(', '));
  }

  return parts.join('\n');
}

/**
 * Inline edit field specialized for addresses with structured editing.
 */
export function InlineEditAddressField({
  value,
  onSave,
  placeholder = 'Add address',
  validation,
  disabled = false,
  className,
  'data-testid': testId,
  'aria-label': ariaLabel,
  showIcon = true,
}: InlineEditAddressFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  // Parse initial value
  const initialAddressData =
    typeof value === 'string' ? parseAddressString(value) : value || {};

  const [addressData, setAddressData] =
    useState<AddressData>(initialAddressData);
  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Format for display
  const displayValue = formatAddressForDisplay(value);

  // Generate unique IDs for accessibility
  const baseId = useId();
  const streetId = `address-street-${baseId}`;
  const street2Id = `address-street2-${baseId}`;
  const cityId = `address-city-${baseId}`;
  const regionId = `address-region-${baseId}`;
  const postalId = `address-postal-${baseId}`;

  // Focus first input when entering edit mode
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isEditing]);

  const startEdit = useCallback(() => {
    setIsEditing(true);
    setError(null);
    // Reset to current value
    const currentData =
      typeof value === 'string' ? parseAddressString(value) : value || {};
    setAddressData(currentData);
  }, [value]);

  const cancelEdit = useCallback(() => {
    setIsEditing(false);
    setError(null);
    // Reset to original value
    const originalData =
      typeof value === 'string' ? parseAddressString(value) : value || {};
    setAddressData(originalData);
  }, [value]);

  const saveEdit = useCallback(async () => {
    // Run validation if provided
    if (validation) {
      const validationError = validation(addressData);
      if (validationError) {
        setError(validationError);
        return;
      }
    }

    setIsLoading(true);
    setError(null);
    setIsEditing(false);

    try {
      await onSave(addressData);
    } catch (saveError) {
      // Rollback
      setIsEditing(true);
      const errorMessage =
        saveError instanceof Error
          ? saveError.message
          : 'Failed to save address';
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, [addressData, validation, onSave]);

  const handleFieldChange = useCallback(
    (field: keyof AddressData, fieldValue: string) => {
      setAddressData(prev => ({
        ...prev,
        [field]: fieldValue || undefined,
      }));
    },
    []
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        cancelEdit();
        return;
      }

      if (event.key === 'Enter') {
        event.preventDefault();
        // Handle keyboard navigation: Enter for next field, Shift+Enter for previous field
        const currentElement = event.target as HTMLInputElement;
        const form =
          currentElement.closest('form') ||
          currentElement.closest('[role="form"]') ||
          currentElement.parentElement;
        if (form) {
          const inputs = Array.from(
            form.querySelectorAll('input:not([disabled])')
          ) as HTMLInputElement[];
          const currentIndex = inputs.indexOf(currentElement);

          if (event.shiftKey) {
            // Shift+Enter: Move to previous field
            const previousInput = inputs[currentIndex - 1];
            if (previousInput) {
              previousInput.focus();
            }
          } else {
            // Enter: Move to next field or save if on last field
            const nextInput = inputs[currentIndex + 1];
            if (nextInput) {
              nextInput.focus();
            } else {
              // If we're on the last field, save the address
              saveEdit();
            }
          }
        }
      }
    },
    [cancelEdit, saveEdit]
  );

  // Edit mode
  if (isEditing) {
    return (
      <div
        className={cn(
          'bg-background inline-flex flex-col gap-3 rounded-md border p-3',
          className
        )}
        data-testid={testId}
      >
        <div className='grid grid-cols-1 gap-2'>
          <div>
            <Label htmlFor={streetId} className='text-xs font-medium'>
              Street Address
            </Label>
            <Input
              ref={inputRef}
              id={streetId}
              value={addressData.street_line_1 || ''}
              onChange={e => handleFieldChange('street_line_1', e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              placeholder='123 Main Street'
              className='h-8'
            />
          </div>

          <div>
            <Label htmlFor={street2Id} className='text-xs font-medium'>
              Apartment, suite, etc. (optional)
            </Label>
            <Input
              id={street2Id}
              value={addressData.street_line_2 || ''}
              onChange={e => handleFieldChange('street_line_2', e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              placeholder='Apt 4B'
              className='h-8'
            />
          </div>

          <div className='grid grid-cols-2 gap-2'>
            <div>
              <Label htmlFor={cityId} className='text-xs font-medium'>
                City
              </Label>
              <Input
                id={cityId}
                value={addressData.locality || ''}
                onChange={e => handleFieldChange('locality', e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
                placeholder='Sydney'
                className='h-8'
              />
            </div>

            <div>
              <Label htmlFor={regionId} className='text-xs font-medium'>
                State/Province
              </Label>
              <Input
                id={regionId}
                value={addressData.region || ''}
                onChange={e => handleFieldChange('region', e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
                placeholder='NSW'
                className='h-8'
              />
            </div>
          </div>

          <div className='grid grid-cols-2 gap-2'>
            <div>
              <Label htmlFor={postalId} className='text-xs font-medium'>
                Postal Code
              </Label>
              <Input
                id={postalId}
                value={addressData.postal_code || ''}
                onChange={e => handleFieldChange('postal_code', e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isLoading}
                placeholder='2000'
                className='h-8'
              />
            </div>
          </div>
        </div>

        {error && (
          <div className='text-destructive text-sm' role='alert'>
            {error}
          </div>
        )}

        <div className='flex items-center gap-1'>
          <Button
            type='button'
            size='sm'
            onClick={saveEdit}
            disabled={isLoading}
            className='h-7 px-2'
          >
            <Check className='h-3 w-3' />
            <span className='sr-only'>Save address</span>
          </Button>
          <Button
            type='button'
            variant='outline'
            size='sm'
            onClick={cancelEdit}
            disabled={isLoading}
            className='h-7 px-2'
          >
            <X className='h-3 w-3' />
            <span className='sr-only'>Cancel editing</span>
          </Button>
        </div>
      </div>
    );
  }

  // View mode
  const displayText = displayValue || placeholder;
  const isEmpty = !displayValue;

  return (
    <div className='inline-flex items-start gap-2'>
      {showIcon && (
        <MapPin
          className='text-muted-foreground mt-1 h-4 w-4 flex-shrink-0'
          aria-hidden='true'
        />
      )}
      <button
        type='button'
        className={cn(
          'inline-flex min-h-[32px] cursor-pointer items-start rounded-md px-2 py-1 text-left text-sm transition-colors',
          'hover:bg-muted focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
          disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent',
          isEmpty && 'text-muted-foreground italic',
          className
        )}
        disabled={disabled}
        onClick={startEdit}
        aria-label={
          ariaLabel || `Click to edit ${displayValue || 'empty address'}`
        }
        data-testid={testId}
      >
        <span className='whitespace-pre-line'>{displayText}</span>
      </button>
    </div>
  );
}
