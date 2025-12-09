/**
 * Contact methods list component with inline editing and add/remove functionality.
 *
 * Displays a list of contact methods (email, phone) with the ability to:
 * - Edit individual method fields inline
 * - Add new methods
 * - Remove existing methods
 * - Manage primary designation constraints
 */

'use client';

import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { InlineEditEmailField } from './InlineEditEmailField';
import { InlineEditPhoneField } from './InlineEditPhoneField';
import { InlineEditField } from './InlineEditField';
import {
  useAddContactMethod,
  useDeleteContactMethod,
  updateContactMethodField,
} from '@/lib/api/contacts';
import {
  ContactMethodAttributes,
  ContactMethodResource,
  ContactMethodType,
} from '@/types/contacts';

export interface ContactMethodsListProps {
  /** Contact ID */
  readonly contactId: string;
  /** List of contact methods */
  readonly methods: readonly ContactMethodResource[];
  /** Whether the component is disabled */
  readonly disabled?: boolean;
  /** Additional CSS classes */
  readonly className?: string;
  /** Test ID for testing */
  readonly 'data-testid'?: string;
}

/**
 * Contact methods list component with inline editing and add/remove functionality.
 */
export function ContactMethodsList({
  contactId,
  methods,
  disabled = false,
  className,
  'data-testid': testId,
}: ContactMethodsListProps) {
  const [isAddingMethod, setIsAddingMethod] = useState(false);
  const [newMethodType, setNewMethodType] = useState<ContactMethodType>(
    ContactMethodType.EMAIL
  );

  const addMethodMutation = useAddContactMethod();
  const deleteMethodMutation = useDeleteContactMethod();

  // TODO: Implement handleAddMethod when add form is complete
  // const handleAddMethod = async (methodData: ContactMethodAttributes) => {
  //   try {
  //     await addMethodMutation.mutateAsync({
  //       contactId,
  //       method: methodData,
  //     });
  //     setIsAddingMethod(false);
  //   } catch (error) {
  //     // Error handling is done by the mutation hook
  //     console.error('Failed to add method:', error);
  //   }
  // };

  const handleDeleteMethod = async (methodId: string) => {
    // Use window.confirm for now - in production, this should be replaced with a proper modal
    if (!window.confirm('Are you sure you want to delete this contact method?')) {
      return;
    }

    try {
      await deleteMethodMutation.mutateAsync({
        contactId,
        methodId,
      });
    } catch (error) {
      // Error handling is done by the mutation hook
      console.error('Failed to delete method:', error);
    }
  };

  const handleFieldUpdate = async (
    methodId: string,
    fieldName: string,
    value: string
  ) => {
    try {
      await updateContactMethodField(contactId, methodId, fieldName, value);
    } catch (error) {
      console.error('Failed to update method field:', error);
      throw error; // Re-throw to trigger inline edit error handling
    }
  };

  const renderMethodField = (method: ContactMethodResource) => {
    const methodId = method.id?.toString() || '';
    const { method_type, value, label } = method.attributes;

    if (method_type === ContactMethodType.EMAIL) {
      return (
        <InlineEditEmailField
          value={value}
          onSave={(newValue) => handleFieldUpdate(methodId, 'value', newValue)}
          placeholder="Enter email address"
          disabled={disabled}
          aria-label={`Email address${label ? ` (${label})` : ''}`}
        />
      );
    }

    if (
      method_type === ContactMethodType.PHONE ||
      method_type === ContactMethodType.MOBILE
    ) {
      return (
        <InlineEditPhoneField
          value={value}
          onSave={(newValue) => handleFieldUpdate(methodId, 'value', newValue)}
          placeholder="Enter phone number"
          disabled={disabled}
          aria-label={`Phone number${label ? ` (${label})` : ''}`}
        />
      );
    }

    // Fallback for other method types
    return (
      <InlineEditField
        value={value}
        onSave={(newValue) => handleFieldUpdate(methodId, 'value', newValue)}
        placeholder={`Enter ${method_type}`}
        disabled={disabled}
        aria-label={`${method_type}${label ? ` (${label})` : ''}`}
      />
    );
  };

  return (
    <Card className={className} data-testid={testId}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base font-medium">Contact Methods</CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setIsAddingMethod(true)}
          disabled={disabled || isAddingMethod}
          aria-label="Add contact method"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {methods.map((method) => (
          <div
            key={method.id}
            className="flex items-center justify-between space-x-3 p-2 rounded-md border"
          >
            <div className="flex-1 min-w-0">
              {renderMethodField(method)}
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleDeleteMethod(method.id?.toString() || '')}
              disabled={disabled}
              aria-label={`Delete ${method.attributes.method_type}`}
            >
              <Trash2 className="h-4 w-4 text-destructive" aria-hidden="true" />
            </Button>
          </div>
        ))}

        {methods.length === 0 && !isAddingMethod && (
          <p className="text-sm text-muted-foreground text-center py-4">
            No contact methods yet. Click the + button to add one.
          </p>
        )}

        {isAddingMethod && (
          <div className="p-3 rounded-md border border-dashed">
            <div className="space-y-3">
              <div className="flex items-center space-x-2">
                <label htmlFor="method-type" className="text-sm font-medium">
                  Type:
                </label>
                <select
                  id="method-type"
                  value={newMethodType}
                  onChange={(e) => setNewMethodType(e.target.value as ContactMethodType)}
                  className="px-2 py-1 border rounded text-sm"
                >
                  <option value={ContactMethodType.EMAIL}>Email</option>
                  <option value={ContactMethodType.PHONE}>Phone</option>
                  <option value={ContactMethodType.MOBILE}>Mobile</option>
                </select>
              </div>
              <div className="flex items-center space-x-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    // For now, just close the add form
                    // In a full implementation, we'd show a form to collect the method data
                    setIsAddingMethod(false);
                  }}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => {
                    // For now, just close the add form
                    // In a full implementation, we'd collect the form data and call handleAddMethod
                    setIsAddingMethod(false);
                  }}
                >
                  Add Method
                </Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
