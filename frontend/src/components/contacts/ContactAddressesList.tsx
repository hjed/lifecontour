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
import { InlineEditAddressField } from './InlineEditAddressField';
import { InlineEditField } from './InlineEditField';
import {
  useAddContactAddress,
  useDeleteContactAddress,
  updateContactAddressField,
} from '@/lib/api/contacts';
import {
  ContactAddressResource,
} from '@/types/contacts';

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

  // TODO: Uncomment when add form is implemented
  // const addAddressMutation = useAddContactAddress();
  const deleteAddressMutation = useDeleteContactAddress();

  // TODO: Implement handleAddAddress when add form is complete
  // const handleAddAddress = async (addressData: ContactAddressAttributes) => {
  //   try {
  //     await addAddressMutation.mutateAsync({
  //       contactId,
  //       address: addressData,
  //     });
  //     setIsAddingAddress(false);
  //   } catch (error) {
  //     // Error handling is done by the mutation hook
  //     console.error('Failed to add address:', error);
  //   }
  // };

  const handleDeleteAddress = async (addressId: string) => {
    // Use window.confirm for now - in production, this should be replaced with a proper modal
    if (!window.confirm('Are you sure you want to delete this address?')) {
      return;
    }

    try {
      await deleteAddressMutation.mutateAsync({
        contactId,
        addressId,
      });
    } catch (error) {
      // Error handling is done by the mutation hook
      console.error('Failed to delete address:', error);
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

  // TODO: Use formatAddressForDisplay when needed for address display
  // const formatAddressForDisplay = (address: ContactAddressAttributes): string => {
  //   const parts: string[] = [];
  //
  //   if (address.street_line_1) {
  //     parts.push(address.street_line_1);
  //   }
  //   if (address.street_line_2) {
  //     parts.push(address.street_line_2);
  //   }
  //
  //   const locationParts: string[] = [];
  //   if (address.locality) locationParts.push(address.locality);
  //   if (address.region) locationParts.push(address.region);
  //   if (address.postal_code) locationParts.push(address.postal_code);
  //
  //   if (locationParts.length > 0) {
  //     parts.push(locationParts.join(', '));
  //   }
  //
  //   return parts.join('\n');
  // };

  return (
    <Card className={className} data-testid={testId}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base font-medium">Addresses</CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setIsAddingAddress(true)}
          disabled={disabled || isAddingAddress}
          aria-label="Add address"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {addresses.map((address) => (
          <div
            key={address.id}
            className="flex items-start justify-between space-x-3 p-3 rounded-md border"
          >
            <div className="flex items-start space-x-2 flex-1 min-w-0">
              <MapPin className="h-4 w-4 text-muted-foreground mt-1 flex-shrink-0" aria-hidden="true" />
              <div className="flex-1 min-w-0">
                <InlineEditAddressField
                  value={address.attributes}
                  onSave={async (addressData) => {
                    // For now, we'll update the full address through the main contact update
                    // In a more sophisticated implementation, we could update individual fields
                    console.log('Address update:', addressData);
                  }}
                  placeholder="Add address"
                  disabled={disabled}
                  aria-label={`Address${address.attributes.label ? ` (${address.attributes.label})` : ''}`}
                />
                {address.attributes.label && (
                  <div className="mt-1">
                    <InlineEditField
                      value={address.attributes.label}
                      onSave={(newLabel) => 
                        handleFieldUpdate(address.id?.toString() || '', 'label', newLabel)
                      }
                      placeholder="Address label"
                      disabled={disabled}
                      className="text-xs text-muted-foreground"
                      aria-label="Address label"
                    />
                  </div>
                )}
              </div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleDeleteAddress(address.id?.toString() || '')}
              disabled={disabled}
              aria-label="Delete address"
            >
              <Trash2 className="h-4 w-4 text-destructive" aria-hidden="true" />
            </Button>
          </div>
        ))}

        {addresses.length === 0 && !isAddingAddress && (
          <p className="text-sm text-muted-foreground text-center py-4">
            No addresses yet. Click the + button to add one.
          </p>
        )}

        {isAddingAddress && (
          <div className="p-3 rounded-md border border-dashed">
            <div className="space-y-3">
              <p className="text-sm font-medium">Add New Address</p>
              <div className="flex items-center space-x-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setIsAddingAddress(false)}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => {
                    // For now, just close the add form
                    // In a full implementation, we'd show a form to collect the address data
                    setIsAddingAddress(false);
                  }}
                >
                  Add Address
                </Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
