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
import { InlineEditEmailField } from './InlineEditEmailField';
import { InlineEditPhoneField } from './InlineEditPhoneField';
import { InlineEditField } from './InlineEditField';
import {
  useAddContactMethod,
  useDeleteContactMethod,
  updateContactMethodField,
} from '@/lib/api/contacts';
import {
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
  const [newMethodValue, setNewMethodValue] = useState('');
  const [newMethodLabel, setNewMethodLabel] = useState('');
  const [newMethodIsPrimary, setNewMethodIsPrimary] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [methodToDelete, setMethodToDelete] = useState<string | null>(null);

  const addMethodMutation = useAddContactMethod();
  const deleteMethodMutation = useDeleteContactMethod();

  const resetAddForm = () => {
    setNewMethodType(ContactMethodType.EMAIL);
    setNewMethodValue('');
    setNewMethodLabel('');
    setNewMethodIsPrimary(false);
    setIsAddingMethod(false);
  };

  const handleAddMethod = async () => {
    if (!newMethodValue.trim()) {
      return;
    }

    try {
      await addMethodMutation.mutateAsync({
        contactId,
        method: {
          method_type: newMethodType,
          value: newMethodValue.trim(),
          label: newMethodLabel.trim() || undefined,
          is_primary: newMethodIsPrimary,
        },
      });
      resetAddForm();
    } catch (error) {
      // Error handling is done by the mutation hook
      console.error('Failed to add method:', error);
    }
  };

  const handleDeleteClick = (methodId: string) => {
    setMethodToDelete(methodId);
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!methodToDelete) return;

    try {
      await deleteMethodMutation.mutateAsync({
        contactId,
        methodId: methodToDelete,
      });
    } catch (error) {
      // Error handling is done by the mutation hook
      console.error('Failed to delete method:', error);
    } finally {
      setDeleteDialogOpen(false);
      setMethodToDelete(null);
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
              onClick={() => handleDeleteClick(method.id?.toString() || '')}
              disabled={disabled || deleteMethodMutation.isPending}
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
          <div className="p-3 rounded-md border border-dashed space-y-4">
            <div className="space-y-2">
              <Label htmlFor="method-type">Type</Label>
              <Select
                value={newMethodType}
                onValueChange={(value) => setNewMethodType(value as ContactMethodType)}
              >
                <SelectTrigger id="method-type">
                  <SelectValue placeholder="Select type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ContactMethodType.EMAIL}>Email</SelectItem>
                  <SelectItem value={ContactMethodType.PHONE}>Phone</SelectItem>
                  <SelectItem value={ContactMethodType.MOBILE}>Mobile</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="method-value">
                {newMethodType === ContactMethodType.EMAIL ? 'Email Address' : 'Phone Number'} *
              </Label>
              <Input
                id="method-value"
                type={newMethodType === ContactMethodType.EMAIL ? 'email' : 'tel'}
                value={newMethodValue}
                onChange={(e) => setNewMethodValue(e.target.value)}
                placeholder={newMethodType === ContactMethodType.EMAIL ? 'email@example.com' : '+1 234 567 8900'}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="method-label">Label (optional)</Label>
              <Input
                id="method-label"
                value={newMethodLabel}
                onChange={(e) => setNewMethodLabel(e.target.value)}
                placeholder="e.g., Work, Personal"
              />
            </div>

            <div className="flex items-center space-x-2">
              <Checkbox
                id="method-primary"
                checked={newMethodIsPrimary}
                onCheckedChange={(checked) => setNewMethodIsPrimary(checked === true)}
              />
              <Label htmlFor="method-primary" className="text-sm font-normal">
                Set as primary
              </Label>
            </div>

            <div className="flex items-center space-x-2 pt-2">
              <Button
                variant="outline"
                size="sm"
                onClick={resetAddForm}
                disabled={addMethodMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleAddMethod}
                disabled={!newMethodValue.trim() || addMethodMutation.isPending}
              >
                {addMethodMutation.isPending ? 'Adding...' : 'Add Method'}
              </Button>
            </div>
          </div>
        )}
      </CardContent>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete Contact Method</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this contact method? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteDialogOpen(false)}
              disabled={deleteMethodMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirmDelete}
              disabled={deleteMethodMutation.isPending}
            >
              {deleteMethodMutation.isPending ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
