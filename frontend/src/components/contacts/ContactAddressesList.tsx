/**
 * Contact addresses list component with inline editing and add/remove functionality.
 *
 * Displays a list of contact addresses with the ability to:
 * - Edit individual address fields inline
 * - Add new addresses
 * - Remove existing addresses
 * - Manage primary designation constraints
 */

'use client';

import { useState } from 'react';
import { Plus, Trash2, MapPin } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { InlineEditAddressField } from './InlineEditAddressField';
import { InlineEditField } from './InlineEditField';
import {
  useAddContactAddress,
  useDeleteContactAddress,
  updateContactAddressField,
} from '@/lib/api/contacts';
import {
  ContactAddressResource,
  ContactAddressAttributes,
} from '@/types/contacts';
import { AddressData } from './InlineEditAddressField';

// Common country codes for the select dropdown
const COMMON_COUNTRIES = [
  { code: 'AU', name: 'Australia' },
  { code: 'US', name: 'United States' },
  { code: 'GB', name: 'United Kingdom' },
  { code: 'CA', name: 'Canada' },
  { code: 'NZ', name: 'New Zealand' },
  { code: 'DE', name: 'Germany' },
  { code: 'FR', name: 'France' },
  { code: 'JP', name: 'Japan' },
  { code: 'CN', name: 'China' },
  { code: 'IN', name: 'India' },
];

export interface ContactAddressesListProps {
  /** Contact ID */
  readonly contactId: string;
  /** List of contact addresses */
  readonly addresses: readonly ContactAddressResource[];
  /** Whether the component is disabled */
  readonly disabled?: boolean;
  /** Additional CSS classes */
  readonly className?: string;
  /** Test ID for testing */
  readonly 'data-testid'?: string;
}

// Initial state for new address form
const initialAddressState: Omit<ContactAddressAttributes, 'is_primary'> & {
  is_primary: boolean;
} = {
  street_line_1: '',
  street_line_2: '',
  locality: '',
  region: '',
  postal_code: '',
  country_code: 'AU',
  label: '',
  is_primary: false,
};

/**
 * Contact addresses list component with inline editing and add/remove functionality.
 */
export function ContactAddressesList({
  contactId,
  addresses,
  disabled = false,
  className,
  'data-testid': testId,
}: ContactAddressesListProps) {
  const [isAddingAddress, setIsAddingAddress] = useState(false);
  const [newAddress, setNewAddress] = useState(initialAddressState);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [addressToDelete, setAddressToDelete] = useState<string | null>(null);

  const addAddressMutation = useAddContactAddress();
  const deleteAddressMutation = useDeleteContactAddress();

  const resetAddForm = () => {
    setNewAddress(initialAddressState);
    setIsAddingAddress(false);
  };

  const handleAddAddress = async () => {
    if (!newAddress.street_line_1.trim()) {
      return;
    }

    try {
      await addAddressMutation.mutateAsync({
        contactId,
        address: {
          street_line_1: newAddress.street_line_1.trim(),
          street_line_2: newAddress.street_line_2?.trim() || undefined,
          locality: newAddress.locality?.trim() || undefined,
          region: newAddress.region?.trim() || undefined,
          postal_code: newAddress.postal_code?.trim() || undefined,
          country_code: newAddress.country_code,
          label: newAddress.label?.trim() || undefined,
          is_primary: newAddress.is_primary,
        },
      });
      resetAddForm();
    } catch (error) {
      // Error handling is done by the mutation hook
      console.error('Failed to add address:', error);
    }
  };

  const handleDeleteClick = (addressId: string) => {
    setAddressToDelete(addressId);
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!addressToDelete) return;

    try {
      await deleteAddressMutation.mutateAsync({
        contactId,
        addressId: addressToDelete,
      });
    } catch (error) {
      // Error handling is done by the mutation hook
      console.error('Failed to delete address:', error);
    } finally {
      setDeleteDialogOpen(false);
      setAddressToDelete(null);
    }
  };

  const handleFieldUpdate = async (
    addressId: string,
    fieldName: string,
    value: string
  ) => {
    try {
      await updateContactAddressField(contactId, addressId, fieldName, value);
    } catch (error) {
      console.error('Failed to update address field:', error);
      throw error; // Re-throw to trigger inline edit error handling
    }
  };

  const handleAddressUpdate = async (
    addressId: string,
    addressData: AddressData
  ) => {
    // Update each field that has changed
    const fieldUpdates = [
      { field: 'street_line_1', value: addressData.street_line_1 || '' },
      { field: 'street_line_2', value: addressData.street_line_2 || '' },
      { field: 'locality', value: addressData.locality || '' },
      { field: 'region', value: addressData.region || '' },
      { field: 'postal_code', value: addressData.postal_code || '' },
      { field: 'country_code', value: addressData.country_code || '' },
    ];

    for (const { field, value } of fieldUpdates) {
      await handleFieldUpdate(addressId, field, value);
    }
  };

  return (
    <Card className={className} data-testid={testId}>
      <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
        <CardTitle className='text-base font-medium'>Addresses</CardTitle>
        <Button
          variant='outline'
          size='sm'
          onClick={() => setIsAddingAddress(true)}
          disabled={disabled || isAddingAddress}
          aria-label='Add address'
        >
          <Plus className='h-4 w-4' aria-hidden='true' />
        </Button>
      </CardHeader>
      <CardContent className='space-y-3'>
        {addresses.map(address => (
          <div
            key={address.id}
            className='flex items-start justify-between space-x-3 rounded-md border p-3'
          >
            <div className='flex min-w-0 flex-1 items-start space-x-2'>
              <MapPin
                className='text-muted-foreground mt-1 h-4 w-4 flex-shrink-0'
                aria-hidden='true'
              />
              <div className='min-w-0 flex-1'>
                <InlineEditAddressField
                  value={address.attributes}
                  onSave={addressData =>
                    handleAddressUpdate(
                      address.id?.toString() || '',
                      addressData
                    )
                  }
                  placeholder='Add address'
                  disabled={disabled}
                  aria-label={`Address${address.attributes.label ? ` (${address.attributes.label})` : ''}`}
                />
                {address.attributes.label && (
                  <div className='mt-1'>
                    <InlineEditField
                      value={address.attributes.label}
                      onSave={newLabel =>
                        handleFieldUpdate(
                          address.id?.toString() || '',
                          'label',
                          newLabel
                        )
                      }
                      placeholder='Address label'
                      disabled={disabled}
                      className='text-muted-foreground text-xs'
                      aria-label='Address label'
                    />
                  </div>
                )}
              </div>
            </div>
            <Button
              variant='ghost'
              size='sm'
              onClick={() => handleDeleteClick(address.id?.toString() || '')}
              disabled={disabled || deleteAddressMutation.isPending}
              aria-label='Delete address'
            >
              <Trash2 className='text-destructive h-4 w-4' aria-hidden='true' />
            </Button>
          </div>
        ))}

        {addresses.length === 0 && !isAddingAddress && (
          <p className='text-muted-foreground py-4 text-center text-sm'>
            No addresses yet. Click the + button to add one.
          </p>
        )}

        {isAddingAddress && (
          <div className='space-y-4 rounded-md border border-dashed p-3'>
            <p className='text-sm font-medium'>Add New Address</p>

            <div className='space-y-2'>
              <Label htmlFor='street-line-1'>Street Address *</Label>
              <Input
                id='street-line-1'
                value={newAddress.street_line_1}
                onChange={e =>
                  setNewAddress({
                    ...newAddress,
                    street_line_1: e.target.value,
                  })
                }
                placeholder='123 Main Street'
              />
            </div>

            <div className='space-y-2'>
              <Label htmlFor='street-line-2'>Street Address Line 2</Label>
              <Input
                id='street-line-2'
                value={newAddress.street_line_2 || ''}
                onChange={e =>
                  setNewAddress({
                    ...newAddress,
                    street_line_2: e.target.value,
                  })
                }
                placeholder='Apt, Suite, Unit, etc.'
              />
            </div>

            <div className='grid grid-cols-2 gap-4'>
              <div className='space-y-2'>
                <Label htmlFor='locality'>City</Label>
                <Input
                  id='locality'
                  value={newAddress.locality || ''}
                  onChange={e =>
                    setNewAddress({ ...newAddress, locality: e.target.value })
                  }
                  placeholder='Sydney'
                />
              </div>
              <div className='space-y-2'>
                <Label htmlFor='region'>State/Region</Label>
                <Input
                  id='region'
                  value={newAddress.region || ''}
                  onChange={e =>
                    setNewAddress({ ...newAddress, region: e.target.value })
                  }
                  placeholder='NSW'
                />
              </div>
            </div>

            <div className='grid grid-cols-2 gap-4'>
              <div className='space-y-2'>
                <Label htmlFor='postal-code'>Postal Code</Label>
                <Input
                  id='postal-code'
                  value={newAddress.postal_code || ''}
                  onChange={e =>
                    setNewAddress({
                      ...newAddress,
                      postal_code: e.target.value,
                    })
                  }
                  placeholder='2000'
                />
              </div>
              <div className='space-y-2'>
                <Label htmlFor='country-code'>Country</Label>
                <Select
                  value={newAddress.country_code}
                  onValueChange={value =>
                    setNewAddress({ ...newAddress, country_code: value })
                  }
                >
                  <SelectTrigger id='country-code'>
                    <SelectValue placeholder='Select country' />
                  </SelectTrigger>
                  <SelectContent>
                    {COMMON_COUNTRIES.map(country => (
                      <SelectItem key={country.code} value={country.code}>
                        {country.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className='space-y-2'>
              <Label htmlFor='address-label'>Label (optional)</Label>
              <Input
                id='address-label'
                value={newAddress.label || ''}
                onChange={e =>
                  setNewAddress({ ...newAddress, label: e.target.value })
                }
                placeholder='e.g., Home, Work'
              />
            </div>

            <div className='flex items-center space-x-2'>
              <Checkbox
                id='address-primary'
                checked={newAddress.is_primary}
                onCheckedChange={checked =>
                  setNewAddress({ ...newAddress, is_primary: checked === true })
                }
              />
              <Label htmlFor='address-primary' className='text-sm font-normal'>
                Set as primary address
              </Label>
            </div>

            <div className='flex items-center space-x-2 pt-2'>
              <Button
                variant='outline'
                size='sm'
                onClick={resetAddForm}
                disabled={addAddressMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                size='sm'
                onClick={handleAddAddress}
                disabled={
                  !newAddress.street_line_1.trim() ||
                  addAddressMutation.isPending
                }
              >
                {addAddressMutation.isPending ? 'Adding...' : 'Add Address'}
              </Button>
            </div>
          </div>
        )}
      </CardContent>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete Address</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this address? This action cannot
              be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant='outline'
              onClick={() => setDeleteDialogOpen(false)}
              disabled={deleteAddressMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant='destructive'
              onClick={handleConfirmDelete}
              disabled={deleteAddressMutation.isPending}
            >
              {deleteAddressMutation.isPending ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
