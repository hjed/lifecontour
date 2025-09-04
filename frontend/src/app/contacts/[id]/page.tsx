/**
 * Contact detail page with inline editing capabilities.
 *
 * Displays contact information with the ability to edit inline,
 * following Australian English conventions.
 */

'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { ArrowLeft, Trash2, Mail, Phone, MapPin, Calendar } from 'lucide-react';

import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import { useContact, useDeleteContact } from '@/lib/api/contacts';
import { generateDisplayName } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { ContactIdentityInline } from '@/components/contacts/ContactIdentityInline';
import type { TagResource } from '@/types/contacts';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { DATE_FORMATS } from '@/lib/constants';

// Helper components to reduce duplication
const PrimaryBadge = () => (
  <Badge variant='secondary' className='ml-2 text-xs'>
    Primary
  </Badge>
);

const MetadataItem = ({ label, value }: { label: string; value: string }) => (
  <div className='flex items-center gap-2 text-sm'>
    <Calendar className='text-muted-foreground h-4 w-4' />
    <div>
      <p className='font-medium'>{label}</p>
      <p className='text-muted-foreground'>{value}</p>
    </div>
  </div>
);

const TagsCard = ({
  tags,
  title = 'Tags',
}: {
  tags: TagResource[];
  title?: string;
}) =>
  tags.length > 0 ? (
    <Card>
      <CardHeader>
        <CardTitle className='text-lg'>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className='flex flex-wrap gap-2'>
          {tags.map(tag => (
            <Badge key={tag.id} variant='secondary'>
              {tag.attributes.name}
            </Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  ) : null;

const ContactMethodItem = ({ method }: { method: any }) => (
  <div className='flex items-center gap-3'>
    {method.attributes.method_type === 'email' && (
      <Mail className='text-muted-foreground h-4 w-4' />
    )}
    {method.attributes.method_type === 'phone' && (
      <Phone className='text-muted-foreground h-4 w-4' />
    )}
    <div>
      <p className='text-sm'>
        {method.attributes.value}
        {method.attributes.is_primary && <PrimaryBadge />}
      </p>
      {method.attributes.label && (
        <p className='text-muted-foreground text-xs'>
          {method.attributes.label}
        </p>
      )}
    </div>
  </div>
);

const AddressItem = ({ address }: { address: any }) => (
  <div className='flex items-start gap-3'>
    <MapPin className='text-muted-foreground mt-0.5 h-4 w-4' />
    <div>
      <p className='text-sm'>
        {address.attributes.street_line_1}
        {address.attributes.is_primary && <PrimaryBadge />}
      </p>
      {address.attributes.street_line_2 && (
        <p className='text-muted-foreground text-sm'>
          {address.attributes.street_line_2}
        </p>
      )}
      <p className='text-muted-foreground text-sm'>
        {address.attributes.locality}, {address.attributes.region}{' '}
        {address.attributes.postal_code}
      </p>
      <p className='text-muted-foreground text-sm'>
        {address.attributes.country_code}
      </p>
      {address.attributes.label && (
        <p className='text-muted-foreground text-xs'>
          {address.attributes.label}
        </p>
      )}
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
  const contactId = params.id as string;

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const { data: contactData, isLoading, error } = useContact(contactId);

  const deleteContactMutation = useDeleteContact();

  const contact = contactData?.data;

  const handleDelete = async () => {
    try {
      await deleteContactMutation.mutateAsync(contactId);
      window.location.href = '/contacts';
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
  const tags = contact.relationships?.tags?.data || [];

  return (
    <div className='container mx-auto px-4 py-8'>
      {/* Header */}
      <div className='mb-6 flex items-center gap-4'>
        <Button
          variant='ghost'
          size='sm'
          onClick={() => (window.location.href = '/contacts')}
        >
          <ArrowLeft className='mr-2 h-4 w-4' />
          Back to Contacts
        </Button>
      </div>

      {/* Contact Header - Three Column Grid Layout */}
      <header className='mb-8 grid grid-cols-1 items-start gap-x-8 gap-y-4 md:grid-cols-[128px,1fr] lg:grid-cols-[128px,1fr,280px]'>
        {/* Column 1: Avatar */}
        <div className='col-start-1'>
          <ContactAvatar
            firstName={contact.attributes.first_name}
            lastName={contact.attributes.last_name}
            size='lg'
            className='h-32 w-32'
          />
        </div>

        {/* Column 2: Identity and Actions */}
        <div className='col-start-1 space-y-4 md:col-start-2'>
          <ContactIdentityInline contact={contact} />

          {/* Action Buttons */}
          <div className='flex gap-2'>
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

        {/* Column 3: Sidebar (hidden on smaller screens) */}
        <aside className='hidden space-y-4 lg:col-start-3 lg:block'>
          {/* Tags */}
          <TagsCard tags={tags} />

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
        </aside>
      </header>

      {/* Contact Details */}
      <div className='grid gap-6 lg:grid-cols-3'>
        <div className='lg:col-span-2'>
          <Card>
            <CardHeader>
              <CardTitle className='text-xl'>Contact Details</CardTitle>
            </CardHeader>
            <CardContent>
              <div className='space-y-6'>
                {/* Contact Methods */}
                {contact.attributes.contact_methods &&
                  contact.attributes.contact_methods.length > 0 && (
                    <div>
                      <h3 className='mb-3 font-semibold'>Contact Methods</h3>
                      <div className='space-y-2'>
                        {contact.attributes.contact_methods.map(method => (
                          <ContactMethodItem
                            key={
                              method.id ||
                              `${method.attributes.method_type}-${method.attributes.value}`
                            }
                            method={method}
                          />
                        ))}
                      </div>
                    </div>
                  )}

                {/* Addresses */}
                {contact.attributes.addresses &&
                  contact.attributes.addresses.length > 0 && (
                    <div>
                      <h3 className='mb-3 font-semibold'>Addresses</h3>
                      <div className='space-y-3'>
                        {contact.attributes.addresses.map(address => (
                          <AddressItem
                            key={
                              address.id ||
                              `${address.attributes.street_line_1}-${address.attributes.postal_code || address.attributes.locality}`
                            }
                            address={address}
                          />
                        ))}
                      </div>
                    </div>
                  )}

                {/* Notes */}
                {contact.attributes.notes &&
                  contact.attributes.notes.length > 0 && (
                    <div>
                      <h3 className='mb-3 font-semibold'>Notes</h3>
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
                    </div>
                  )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Sidebar - Mobile fallback for tags and metadata */}
        <div className='space-y-6 lg:hidden'>
          {/* Tags - Mobile Only */}
          <TagsCard tags={tags} />

          {/* Metadata - Mobile Only */}
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
        </div>
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
    </div>
  );
}
