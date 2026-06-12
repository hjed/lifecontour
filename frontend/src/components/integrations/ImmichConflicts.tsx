'use client';

import { useState } from 'react';
import {
  AlertTriangle,
  Link as LinkIcon,
  Loader2,
  UserPlus,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ContactSearchCombobox } from '@/components/contacts/ContactSearchCombobox';
import { generateDisplayName } from '@/lib/utils';
import {
  useImmichConflicts,
  useResolveImmichConflict,
} from '@/lib/api/integrations';
import type { ImmichConflictData } from '@/types/integrations';

interface ConflictItemProps {
  conflict: ImmichConflictData;
  onResolve: (
    conflictId: string,
    action: 'link' | 'create',
    contactId?: number
  ) => void;
  isResolving: boolean;
}

function ConflictItem({ conflict, onResolve, isResolving }: ConflictItemProps) {
  const [selectedContactId, setSelectedContactId] = useState<number | null>(
    null
  );
  // Display name for a contact chosen via search that isn't one of the
  // candidate chips, so the user can see what Link will act on.
  const [searchedContactLabel, setSearchedContactLabel] = useState<
    string | null
  >(null);
  const { attributes } = conflict;

  const handleLink = () => {
    if (selectedContactId !== null) {
      onResolve(conflict.id, 'link', selectedContactId);
    }
  };

  const handleCreate = () => {
    onResolve(conflict.id, 'create');
  };

  return (
    <div
      className='rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-900/50 dark:bg-amber-900/20'
      data-testid={`conflict-item-${conflict.id}`}
    >
      <div className='flex items-start justify-between gap-4'>
        <div className='min-w-0 flex-1'>
          <div className='flex items-center gap-2'>
            <AlertTriangle className='h-4 w-4 flex-shrink-0 text-amber-600 dark:text-amber-400' />
            <h4 className='truncate text-sm font-medium text-amber-800 dark:text-amber-300'>
              {attributes.externalEntityName || 'Unknown Person'}
            </h4>
            <Badge variant='outline' className='text-xs'>
              Immich Person
            </Badge>
          </div>
          <p className='text-muted-foreground mt-1 text-xs'>
            Immich ID: {attributes.externalEntityId}
          </p>

          {attributes.candidateContacts.length > 0 && (
            <div className='mt-3'>
              <p className='text-xs font-medium text-amber-700 dark:text-amber-400'>
                Possible matches ({attributes.candidateContacts.length}{' '}
                contacts):
              </p>
              <div className='mt-1 flex flex-wrap gap-1'>
                {attributes.candidateContacts.map(candidate => (
                  <button
                    key={candidate.id}
                    type='button'
                    className={`inline-flex items-center rounded-md border px-2 py-1 text-xs transition-colors ${
                      selectedContactId === candidate.id
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-border bg-background hover:bg-accent'
                    }`}
                    onClick={() => {
                      setSelectedContactId(candidate.id);
                      setSearchedContactLabel(null);
                    }}
                    aria-label={`Select ${candidate.name} for linking`}
                    aria-pressed={selectedContactId === candidate.id}
                    data-testid={`conflict-${conflict.id}-candidate-${candidate.id}`}
                  >
                    {candidate.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className='mt-3'>
            <p className='text-xs font-medium text-amber-700 dark:text-amber-400'>
              Or search for a different contact:
            </p>
            <div className='mt-1'>
              <ContactSearchCombobox
                placeholder='Search contacts to link...'
                inputId={`conflict-${conflict.id}-search`}
                onSelect={contact => {
                  setSelectedContactId(Number(contact.id));
                  setSearchedContactLabel(
                    contact.attributes.nick_name?.trim()
                      ? `${generateDisplayName(
                          contact.attributes.first_name,
                          contact.attributes.last_name ?? ''
                        )} (${contact.attributes.nick_name})`
                      : generateDisplayName(
                          contact.attributes.first_name,
                          contact.attributes.last_name ?? ''
                        )
                  );
                }}
              />
            </div>
            {searchedContactLabel && (
              <p
                className='text-muted-foreground mt-1 text-xs'
                data-testid={`conflict-${conflict.id}-selected-search`}
              >
                Selected: {searchedContactLabel}
              </p>
            )}
          </div>
        </div>

        <div className='flex flex-shrink-0 flex-col gap-2'>
          <Button
            size='sm'
            variant='default'
            onClick={handleLink}
            disabled={isResolving || selectedContactId === null}
            aria-label={`Link ${attributes.externalEntityName || 'person'} to selected contact`}
            data-testid={`conflict-link-button-${conflict.id}`}
          >
            {isResolving ? (
              <Loader2 className='mr-1 h-3 w-3 animate-spin' />
            ) : (
              <LinkIcon className='mr-1 h-3 w-3' />
            )}
            Link
          </Button>
          <Button
            size='sm'
            variant='outline'
            onClick={handleCreate}
            disabled={isResolving}
            aria-label={`Create new contact from ${attributes.externalEntityName || 'person'}`}
            data-testid={`conflict-create-button-${conflict.id}`}
          >
            {isResolving ? (
              <Loader2 className='mr-1 h-3 w-3 animate-spin' />
            ) : (
              <UserPlus className='mr-1 h-3 w-3' />
            )}
            Create New
          </Button>
        </div>
      </div>
    </div>
  );
}

interface ImmichConflictsProps {
  connected?: boolean;
}

export function ImmichConflicts({ connected = false }: ImmichConflictsProps) {
  const { data, isLoading } = useImmichConflicts(connected);
  const resolveMutation = useResolveImmichConflict();

  const conflicts = data?.data ?? [];

  // Don't render anything if not connected or no conflicts
  if (!connected || isLoading || conflicts.length === 0) {
    return null;
  }

  const handleResolve = (
    conflictId: string,
    action: 'link' | 'create',
    contactId?: number
  ) => {
    resolveMutation.mutate({
      conflictId,
      request: {
        action,
        ...(action === 'link' && contactId !== undefined
          ? { contact_id: contactId }
          : {}),
      },
    });
  };

  return (
    <div
      className='space-y-3'
      data-testid='immich-conflicts-section'
      role='region'
      aria-label='Immich synchronisation conflicts'
    >
      <div className='flex items-center gap-2'>
        <AlertTriangle className='h-4 w-4 text-amber-600 dark:text-amber-400' />
        <h3 className='text-sm font-medium'>
          Synchronisation Conflicts
          <Badge variant='secondary' className='ml-2'>
            {conflicts.length}
          </Badge>
        </h3>
      </div>
      <p className='text-muted-foreground text-xs'>
        These Immich people matched multiple contacts. Choose the correct
        contact to link or create a new one.
      </p>
      <div className='space-y-2'>
        {conflicts.map(conflict => (
          <ConflictItem
            key={conflict.id}
            conflict={conflict}
            onResolve={handleResolve}
            isResolving={resolveMutation.isPending}
          />
        ))}
      </div>
    </div>
  );
}
