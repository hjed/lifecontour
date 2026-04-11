/**
 * Contact detail page with inline editing capabilities.
 *
 * Displays contact information with the ability to edit inline,
 * following Australian English conventions.
 */

'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, Trash2, Calendar } from 'lucide-react';

import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import { useContact, useDeleteContact } from '@/lib/api/contacts';
import { generateDisplayName } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { ContactIdentityInline } from '@/components/contacts/ContactIdentityInline';
import { ContactMethodsList } from '@/components/contacts/ContactMethodsList';
import { ContactAddressesList } from '@/components/contacts/ContactAddressesList';
import { RelationshipsList } from '@/components/contacts/RelationshipsList';
import { ActivityFeed } from '@/components/contacts/ActivityFeed';
import { ContactJournals } from '@/components/contacts/ContactJournals';
import { ContactTagsEditor } from '@/components/contacts/ContactTagsEditor';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { DATE_FORMATS } from '@/lib/constants';

const MetadataItem = ({ label, value }: { label: string; value: string }) => (
  <div className='flex items-center gap-2 text-sm'>
    <Calendar className='text-muted-foreground h-4 w-4' />
    <div>
      <p className='font-medium'>{label}</p>
      <p className='text-muted-foreground'>{value}</p>
    </div>
  </div>
);

export default function ContactDetailPage() {
  return (
    <AuthGuard>
      <ContactDetailPageContent />
    </AuthGuard>
  );
}

function ContactDetailPageContent() {
  const params = useParams();
  const router = useRouter();
  const contactId = params.id as string;

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const { data: contactData, isLoading, error } = useContact(contactId);

  const deleteContactMutation = useDeleteContact();

  const contact = contactData?.data;

  const handleDelete = async () => {
    try {
      await deleteContactMutation.mutateAsync(contactId);
      router.push('/contacts');
    } catch (error) {
      // Error is handled by the mutation
      console.error('Failed to delete contact:', error);
    }
  };

  if (error) {
    return (
      <div className='container mx-auto px-4 py-8'>
        <Alert variant='destructive' data-testid='error-message'>
          <AlertDescription>
            {error instanceof Error ? error.message : 'Failed to load contact'}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  if (isLoading || !contact) {
    return (
      <div className='container mx-auto px-4 py-8'>
        <div className='mb-6'>
          <Skeleton className='mb-2 h-8 w-32' />
          <Skeleton className='h-4 w-64' />
        </div>
        <Card>
          <CardHeader>
            <Skeleton className='h-8 w-48' />
            <Skeleton className='h-4 w-32' />
          </CardHeader>
          <CardContent>
            <div className='space-y-4'>
              <Skeleton className='h-4 w-full' />
              <Skeleton className='h-4 w-3/4' />
              <Skeleton className='h-4 w-1/2' />
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const fullName = generateDisplayName(
    contact.attributes.first_name,
    contact.attributes.last_name || ''
  );

  return (
    <section
      className='container mx-auto px-4 py-8'
      aria-label='Contact Detail'
    >
      {/* Header */}
      <div className='mb-6 flex items-center gap-4'>
        <Button
          variant='ghost'
          size='sm'
          onClick={() => router.push('/contacts')}
        >
          <ArrowLeft className='mr-2 h-4 w-4' />
          Back to Contacts
        </Button>
      </div>

      <div className='grid grid-cols-1 items-start gap-8 lg:grid-cols-12'>
        {/* Main Content */}
        <div className='space-y-6 lg:col-span-8'>
          {/* Identity Header */}
          <div className='flex flex-col gap-6 sm:flex-row sm:items-start'>
            <ContactAvatar
              firstName={contact.attributes.first_name}
              lastName={contact.attributes.last_name}
              size='lg'
              className='h-32 w-32 shrink-0'
            />
            <div className='flex min-w-0 flex-1 flex-col gap-4'>
              <div className='flex items-start justify-between gap-4'>
                <ContactIdentityInline contact={contact} />

                {/* Action Buttons */}
                <div className='flex shrink-0 gap-2'>
                  <Button
                    variant='outline'
                    size='sm'
                    onClick={() => setShowDeleteConfirm(true)}
                    className='text-destructive hover:text-destructive'
                    aria-label='Delete contact'
                  >
                    <Trash2 className='h-4 w-4' />
                  </Button>
                </div>
              </div>

              {/* Tags Editor */}
              <ContactTagsEditor contactId={contact.id} />
            </div>
          </div>

          <div className='grid grid-cols-1 gap-6 xl:grid-cols-2'>
            {/* Contact Methods */}
            <ContactMethodsList
              contactId={contact.id}
              methods={contact.attributes.contact_methods || []}
            />

            {/* Addresses */}
            <ContactAddressesList
              contactId={contact.id}
              addresses={contact.attributes.addresses || []}
            />
          </div>

          {/* Journals */}
          <ContactJournals contactId={contact.id} />

          {/* Notes */}
          {contact.attributes.notes && contact.attributes.notes.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className='text-xl'>Notes</CardTitle>
              </CardHeader>
              <CardContent>
                <div className='space-y-2'>
                  {contact.attributes.notes.map(note => (
                    <div
                      key={
                        note.id ||
                        `${note.attributes.content.substring(0, 50)}-${note.attributes.created_at}`
                      }
                      className='text-sm'
                    >
                      <p>{note.attributes.content}</p>
                      {note.attributes.created_at && (
                        <p className='text-muted-foreground mt-1 text-xs'>
                          {format(
                            new Date(note.attributes.created_at),
                            DATE_FORMATS.WITH_TIME,
                            { locale: enAU }
                          )}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Sidebar */}
        <aside className='space-y-6 lg:col-span-4'>
          {/* Relationships */}
          <RelationshipsList contactId={contact.id} />

          {/* Metadata */}
          <Card>
            <CardHeader>
              <CardTitle className='text-lg'>Information</CardTitle>
            </CardHeader>
            <CardContent className='space-y-3'>
              <MetadataItem
                label='Created'
                value={format(
                  new Date(contact.attributes.created_at),
                  DATE_FORMATS.LONG,
                  { locale: enAU }
                )}
              />
              {contact.attributes.updated_at !==
                contact.attributes.created_at && (
                <MetadataItem
                  label='Last Updated'
                  value={format(
                    new Date(contact.attributes.updated_at),
                    DATE_FORMATS.LONG,
                    { locale: enAU }
                  )}
                />
              )}
            </CardContent>
          </Card>

          {/* Activity Feed */}
          <ActivityFeed contactId={contact.id} pageSize={5} />
        </aside>
      </div>

      {/* Delete Confirmation Dialog */}
      {showDeleteConfirm && (
        <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/50'>
          <Card className='mx-4 w-full max-w-md'>
            <CardHeader>
              <CardTitle>Delete Contact</CardTitle>
            </CardHeader>
            <CardContent>
              <p className='text-muted-foreground mb-4 text-sm'>
                Are you sure you want to delete {fullName}? This action cannot
                be undone.
              </p>
              <div className='flex justify-end gap-2'>
                <Button
                  variant='outline'
                  onClick={() => setShowDeleteConfirm(false)}
                  disabled={deleteContactMutation.isPending}
                >
                  Cancel
                </Button>
                <Button
                  variant='destructive'
                  onClick={handleDelete}
                  disabled={deleteContactMutation.isPending}
                >
                  {deleteContactMutation.isPending ? 'Deleting...' : 'Delete'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </section>
  );
}
