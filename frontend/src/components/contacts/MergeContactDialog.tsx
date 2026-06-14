'use client';

import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { generateDisplayName } from '@/lib/utils';
import { useContact, useMergeContact } from '@/lib/api/contacts';
import type { ContactResource, MergeContactOverrides } from '@/types/contacts';
import { ContactSearchCombobox } from './ContactSearchCombobox';
import { MergeContactResolutionDialog } from './MergeContactResolutionDialog';

interface MergeContactDialogProps {
  /** The contact whose detail page launched the merge. */
  readonly currentContact: ContactResource;
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  /**
   * Called after a successful merge with the surviving contact's id. The detail
   * page uses this to redirect when the current contact was absorbed.
   */
  readonly onMerged?: (survivorId: string) => void;
}

function contactLabel(contact: ContactResource): string {
  return (
    generateDisplayName(
      contact.attributes.first_name,
      contact.attributes.last_name ?? ''
    ) || 'Unnamed contact'
  );
}

/**
 * Reachable contact-merge flow: pick the other contact, choose which contact
 * survives, then hand off to {@link MergeContactResolutionDialog} for per-field
 * conflict resolution. Mirrors the journal `MergeJournalDialog` structure, with
 * an explicit survivor selector that journals do not need.
 */
export function MergeContactDialog({
  currentContact,
  open,
  onOpenChange,
  onMerged,
}: MergeContactDialogProps) {
  const [selectedContact, setSelectedContact] =
    useState<ContactResource | null>(null);
  const [survivorId, setSurvivorId] = useState<string>(currentContact.id);
  const [resolutionOpen, setResolutionOpen] = useState(false);

  // Fetch the full source contact once chosen so the resolution dialog can
  // compare every identity field (search results carry the same attributes,
  // but the detail fetch keeps the two sides consistent).
  const { data: selectedContactRes } = useContact(selectedContact?.id ?? '');
  const otherContact = selectedContactRes?.data ?? selectedContact;

  const mergeContact = useMergeContact();

  const resetState = () => {
    setSelectedContact(null);
    setSurvivorId(currentContact.id);
    setResolutionOpen(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    onOpenChange(nextOpen);
    if (!nextOpen) {
      resetState();
    }
  };

  const handleSelectSource = (contact: ContactResource) => {
    setSelectedContact(contact);
    // Default to the current contact surviving when a new source is picked.
    setSurvivorId(currentContact.id);
  };

  const handleNext = () => {
    if (!selectedContact) return;
    setResolutionOpen(true);
  };

  const handleResolutionOpenChange = (nextOpen: boolean) => {
    setResolutionOpen(nextOpen);
    if (!nextOpen && !mergeContact.isPending) {
      // Cancelling resolution returns to the (now-closed) selection flow.
      onOpenChange(false);
      resetState();
    }
  };

  const survivorContact =
    survivorId === currentContact.id ? currentContact : otherContact;
  const sourceContact =
    survivorId === currentContact.id ? otherContact : currentContact;

  const handleMerge = async (overrides: MergeContactOverrides) => {
    if (!survivorContact || !sourceContact) return;
    try {
      await mergeContact.mutateAsync({
        survivorId: survivorContact.id,
        sourceId: sourceContact.id,
        overrides,
      });
      onMerged?.(survivorContact.id);
      onOpenChange(false);
      resetState();
    } catch {
      // Surfaced by the mutation's onError toast.
    }
  };

  return (
    <>
      <Dialog open={open && !resolutionOpen} onOpenChange={handleOpenChange}>
        <DialogContent className='sm:max-w-md'>
          <DialogHeader>
            <DialogTitle>Merge Another Contact</DialogTitle>
            <DialogDescription>
              Select another contact to merge with this one, then choose which
              contact survives. The other contact is absorbed and deleted; you
              can resolve any conflicting details on the next screen.
            </DialogDescription>
          </DialogHeader>

          <div className='space-y-4 py-4'>
            <div className='flex flex-col gap-2'>
              <Label htmlFor='merge-contact-search'>Find Contact</Label>
              <ContactSearchCombobox
                inputId='merge-contact-search'
                onSelect={handleSelectSource}
                excludeContactIds={[currentContact.id]}
                placeholder='Search by name...'
              />
            </div>

            {selectedContact && otherContact && (
              <>
                <div className='bg-muted rounded-md p-3 text-sm'>
                  <strong>Selected to merge:</strong>{' '}
                  {contactLabel(otherContact)}
                </div>

                <fieldset className='flex flex-col gap-2'>
                  <legend className='mb-1 text-sm font-medium'>
                    Which contact survives?
                  </legend>
                  <RadioGroup
                    value={survivorId}
                    onValueChange={setSurvivorId}
                    className='space-y-2'
                  >
                    <div className='flex items-center space-x-2'>
                      <RadioGroupItem
                        value={currentContact.id}
                        id={`survivor-${currentContact.id}`}
                        data-testid={`radio-survivor-${currentContact.id}`}
                      />
                      <Label htmlFor={`survivor-${currentContact.id}`}>
                        {contactLabel(currentContact)} (current)
                      </Label>
                    </div>
                    <div className='flex items-center space-x-2'>
                      <RadioGroupItem
                        value={otherContact.id}
                        id={`survivor-${otherContact.id}`}
                        data-testid={`radio-survivor-${otherContact.id}`}
                      />
                      <Label htmlFor={`survivor-${otherContact.id}`}>
                        {contactLabel(otherContact)}
                      </Label>
                    </div>
                  </RadioGroup>
                </fieldset>
              </>
            )}
          </div>

          <DialogFooter>
            <Button variant='outline' onClick={() => handleOpenChange(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleNext}
              disabled={!selectedContact}
              className='bg-primary text-primary-foreground'
            >
              Next
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {resolutionOpen && (
        <MergeContactResolutionDialog
          open={resolutionOpen}
          onOpenChange={handleResolutionOpenChange}
          survivorContact={survivorContact ?? null}
          sourceContact={sourceContact ?? null}
          isPending={mergeContact.isPending}
          onResolve={handleMerge}
        />
      )}
    </>
  );
}
