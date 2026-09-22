'use client';

import { useState } from 'react';
import { AlertCircle, ChevronDown, UserPlus } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ContactSearchCombobox } from '@/components/contacts/ContactSearchCombobox';
import {
  AcceptContactSuggestionVariables,
  useAcceptContactSuggestion,
  useContactSuggestions,
  useIgnoreContactSuggestion,
  useIgnoredContactSuggestions,
  useUnignoreContactSuggestion,
} from '@/lib/api/contact-suggestions';
import type { ContactSuggestionResource } from '@/types/contact-suggestions';
import {
  CreateContactFromSuggestionDialog,
  NewContactNames,
} from './CreateContactFromSuggestionDialog';

type PendingAction =
  | { kind: 'create'; suggestion: ContactSuggestionResource }
  | { kind: 'link'; suggestion: ContactSuggestionResource };

/**
 * People who keep appearing on synced events without being contacts.
 *
 * Each suggestion can become a new contact, be added to an existing one, or be
 * ignored; ignored emails are listed below and can be restored.
 */
export function ContactSuggestionsCard() {
  const suggestions = useContactSuggestions();
  const ignoredList = useIgnoredContactSuggestions();
  const accept = useAcceptContactSuggestion();
  const ignore = useIgnoreContactSuggestion();
  const unignore = useUnignoreContactSuggestion();
  const [pending, setPending] = useState<PendingAction | null>(null);

  // Close the dialog only if it is still the accepted suggestion's: the user
  // may have dismissed it and opened another while the request was in flight.
  const acceptAndClose = (variables: AcceptContactSuggestionVariables) =>
    accept.mutate(variables, {
      onSuccess: () =>
        setPending(current =>
          current?.suggestion.attributes.email === variables.email
            ? null
            : current
        ),
    });

  const items = suggestions.data?.data ?? [];
  const ignored = ignoredList.data?.data ?? [];

  return (
    <Card data-testid='contact-suggestions'>
      <CardHeader>
        <CardTitle className='flex items-center gap-2'>
          <UserPlus className='h-5 w-5' />
          Contact suggestions
        </CardTitle>
        <CardDescription>
          People on five or more of your events who are not contacts yet.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        {suggestions.isLoading ? (
          <p className='text-muted-foreground text-sm'>
            Loading suggestions...
          </p>
        ) : suggestions.error ? (
          <Alert variant='destructive'>
            <AlertCircle className='h-4 w-4' />
            <AlertTitle>Error loading suggestions</AlertTitle>
            <AlertDescription>{suggestions.error.message}</AlertDescription>
          </Alert>
        ) : items.length === 0 ? (
          <p className='text-muted-foreground text-sm'>
            No suggestions right now.
          </p>
        ) : (
          <ul className='divide-border divide-y rounded-lg border'>
            {items.map(item => (
              <SuggestionRow
                key={item.id}
                suggestion={item}
                onCreate={() =>
                  setPending({ kind: 'create', suggestion: item })
                }
                onLink={() => setPending({ kind: 'link', suggestion: item })}
                onIgnore={() => ignore.mutate(item.attributes.email)}
              />
            ))}
          </ul>
        )}

        {ignoredList.error && (
          <Alert variant='destructive'>
            <AlertCircle className='h-4 w-4' />
            <AlertTitle>Error loading ignored suggestions</AlertTitle>
            <AlertDescription>{ignoredList.error.message}</AlertDescription>
          </Alert>
        )}

        {ignored.length > 0 && (
          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button variant='ghost' size='sm' className='group -ml-2'>
                Ignored ({ignored.length})
                <ChevronDown className='ml-1 h-4 w-4 transition-transform group-data-[state=open]:rotate-180' />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <ul className='mt-2 space-y-1'>
                {ignored.map(entry => (
                  <li
                    key={entry.id}
                    className='flex items-center justify-between gap-2 text-sm'
                  >
                    <span className='text-muted-foreground min-w-0 truncate'>
                      {entry.attributes.email}
                    </span>
                    <Button
                      variant='outline'
                      size='sm'
                      aria-label={`Restore ${entry.attributes.email}`}
                      disabled={unignore.isPending}
                      onClick={() => unignore.mutate(entry.attributes.email)}
                    >
                      Restore
                    </Button>
                  </li>
                ))}
              </ul>
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>

      {pending?.kind === 'create' && (
        <CreateContactFromSuggestionDialog
          email={pending.suggestion.attributes.email}
          displayName={pending.suggestion.attributes.display_name}
          isSaving={accept.isPending}
          onClose={() => setPending(null)}
          onCreate={({ first_name, last_name }: NewContactNames) =>
            acceptAndClose({
              email: pending.suggestion.attributes.email,
              target: {
                kind: 'new',
                first_name,
                last_name: last_name || null,
              },
            })
          }
        />
      )}

      {pending?.kind === 'link' && (
        <Dialog open onOpenChange={open => !open && setPending(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add to existing contact</DialogTitle>
              <DialogDescription>
                Choose the contact {pending.suggestion.attributes.email} belongs
                to. It will be linked to every event the email was seen on.
              </DialogDescription>
            </DialogHeader>
            <ContactSearchCombobox
              placeholder='Search contacts...'
              onSelect={contact =>
                acceptAndClose({
                  email: pending.suggestion.attributes.email,
                  target: { kind: 'existing', contact_id: Number(contact.id) },
                })
              }
            />
          </DialogContent>
        </Dialog>
      )}
    </Card>
  );
}

interface SuggestionRowProps {
  readonly suggestion: ContactSuggestionResource;
  readonly onCreate: () => void;
  readonly onLink: () => void;
  readonly onIgnore: () => void;
}

function SuggestionRow({
  suggestion,
  onCreate,
  onLink,
  onIgnore,
}: SuggestionRowProps) {
  const { email, display_name, event_count } = suggestion.attributes;
  return (
    <li
      aria-label={email}
      className='flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between'
    >
      <div className='min-w-0'>
        <p className='truncate font-medium'>{display_name ?? email}</p>
        {display_name && (
          <p className='text-muted-foreground truncate text-sm'>{email}</p>
        )}
        <p className='text-muted-foreground text-xs'>
          Seen on {event_count} events
        </p>
      </div>
      <div className='flex flex-wrap gap-2'>
        <Button
          size='sm'
          aria-label={`Create contact for ${email}`}
          onClick={onCreate}
        >
          Create contact
        </Button>
        <Button
          size='sm'
          variant='outline'
          aria-label={`Add ${email} to an existing contact`}
          onClick={onLink}
        >
          Add to existing
        </Button>
        <Button
          size='sm'
          variant='ghost'
          aria-label={`Ignore ${email}`}
          onClick={onIgnore}
        >
          Ignore
        </Button>
      </div>
    </li>
  );
}
