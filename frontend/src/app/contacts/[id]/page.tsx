/**
 * Contact detail page with inline editing capabilities.
 *
 * Displays contact information with the ability to edit inline,
 * following Australian English conventions.
 */

'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import {
  ArrowLeft,
  Edit,
  X,
  Trash2,
  Mail,
  Phone,
  MapPin,
  Calendar,
} from 'lucide-react';

import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import {
  useContact,
  useUpdateContact,
  useDeleteContact,
} from '@/lib/api/contacts';
import { ContactFormData } from '@/types/contacts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { ContactForm } from '@/components/contacts/ContactForm';
import { FavouriteToggle } from '@/components/contacts/FavouriteToggle';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { DATE_FORMATS } from '@/lib/constants';

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

  const [isEditing, setIsEditing] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const { data: contactData, isLoading, error } = useContact(contactId);

  const updateContactMutation = useUpdateContact();
  const deleteContactMutation = useDeleteContact();

  const contact = contactData?.data;

  const handleEdit = () => {
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
  };

  const handleSave = async (formData: ContactFormData) => {
    try {
      await updateContactMutation.mutateAsync({
        id: contactId,
        data: formData,
      });
      setIsEditing(false);
    } catch (error) {
      // Error is handled by the mutation
      console.error('Failed to update contact:', error);
    }
  };

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
        <Alert variant='destructive'>
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

  const fullName =
    `${contact.attributes.first_name} ${contact.attributes.last_name || ''}`.trim();
  const tags = contact.relationships?.tags?.data || [];

  // Convert contact data to form format
  const formData: ContactFormData = {
    first_name: contact.attributes.first_name,
    last_name: contact.attributes.last_name || '',
    middle_name: contact.attributes.middle_name || '',
    nick_name: contact.attributes.nick_name || '',
    contact_methods: contact.attributes.contact_methods || [],
    addresses: contact.attributes.addresses || [],
    notes: contact.attributes.notes || [],
  };

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

      {/* Contact Information */}
      <div className='grid gap-6 lg:grid-cols-3'>
        <div className='lg:col-span-2'>
          <Card>
            <CardHeader>
              <div className='flex items-start justify-between'>
                <div>
                  <CardTitle className='text-2xl'>{fullName}</CardTitle>
                  {contact.attributes.nick_name && (
                    <p className='text-muted-foreground mt-1'>
                      &ldquo;{contact.attributes.nick_name}&rdquo;
                    </p>
                  )}
                </div>
                <div className='flex gap-2'>
                  {!isEditing && (
                    <>
                      <FavouriteToggle
                        contactId={contact.id}
                        isFavourite={contact.attributes.is_favourite || false}
                        contactName={fullName}
                        size='sm'
                      />
                      <Button variant='outline' size='sm' onClick={handleEdit}>
                        <Edit className='mr-2 h-4 w-4' />
                        Edit
                      </Button>
                      <Button
                        variant='outline'
                        size='sm'
                        onClick={() => setShowDeleteConfirm(true)}
                        className='text-destructive hover:text-destructive'
                        aria-label='Delete contact'
                      >
                        <Trash2 className='h-4 w-4' />
                      </Button>
                    </>
                  )}
                  {isEditing && (
                    <Button
                      variant='outline'
                      size='sm'
                      onClick={handleCancelEdit}
                    >
                      <X className='mr-2 h-4 w-4' />
                      Cancel
                    </Button>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {isEditing ? (
                <ContactForm
                  initialData={formData}
                  onSubmit={handleSave}
                  onCancel={handleCancelEdit}
                  isLoading={updateContactMutation.isPending}
                />
              ) : (
                <div className='space-y-6'>
                  {/* Contact Methods */}
                  {contact.attributes.contact_methods &&
                    contact.attributes.contact_methods.length > 0 && (
                      <div>
                        <h3 className='mb-3 font-semibold'>Contact Methods</h3>
                        <div className='space-y-2'>
                          {contact.attributes.contact_methods.map(
                            (method, index) => (
                              <div
                                key={index}
                                className='flex items-center gap-3'
                              >
                                {method.attributes.method_type === 'email' && (
                                  <Mail className='text-muted-foreground h-4 w-4' />
                                )}
                                {method.attributes.method_type === 'phone' && (
                                  <Phone className='text-muted-foreground h-4 w-4' />
                                )}
                                <div>
                                  <p className='text-sm'>
                                    {method.attributes.value}
                                    {method.attributes.is_primary && (
                                      <Badge
                                        variant='secondary'
                                        className='ml-2 text-xs'
                                      >
                                        Primary
                                      </Badge>
                                    )}
                                  </p>
                                  {method.attributes.label && (
                                    <p className='text-muted-foreground text-xs'>
                                      {method.attributes.label}
                                    </p>
                                  )}
                                </div>
                              </div>
                            )
                          )}
                        </div>
                      </div>
                    )}

                  {/* Addresses */}
                  {contact.attributes.addresses &&
                    contact.attributes.addresses.length > 0 && (
                      <div>
                        <h3 className='mb-3 font-semibold'>Addresses</h3>
                        <div className='space-y-3'>
                          {contact.attributes.addresses.map(
                            (address, index) => (
                              <div
                                key={index}
                                className='flex items-start gap-3'
                              >
                                <MapPin className='text-muted-foreground mt-0.5 h-4 w-4' />
                                <div>
                                  <p className='text-sm'>
                                    {address.attributes.street_line_1}
                                    {address.attributes.is_primary && (
                                      <Badge
                                        variant='secondary'
                                        className='ml-2 text-xs'
                                      >
                                        Primary
                                      </Badge>
                                    )}
                                  </p>
                                  {address.attributes.street_line_2 && (
                                    <p className='text-muted-foreground text-sm'>
                                      {address.attributes.street_line_2}
                                    </p>
                                  )}
                                  <p className='text-muted-foreground text-sm'>
                                    {address.attributes.locality},{' '}
                                    {address.attributes.region}{' '}
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
                            )
                          )}
                        </div>
                      </div>
                    )}

                  {/* Notes */}
                  {contact.attributes.notes &&
                    contact.attributes.notes.length > 0 && (
                      <div>
                        <h3 className='mb-3 font-semibold'>Notes</h3>
                        <div className='space-y-2'>
                          {contact.attributes.notes.map((note, index) => (
                            <div key={index} className='text-sm'>
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
              )}
            </CardContent>
          </Card>
        </div>

        {/* Sidebar */}
        <div className='space-y-6'>
          {/* Tags */}
          {tags.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className='text-lg'>Tags</CardTitle>
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
          )}

          {/* Metadata */}
          <Card>
            <CardHeader>
              <CardTitle className='text-lg'>Information</CardTitle>
            </CardHeader>
            <CardContent className='space-y-3'>
              <div className='flex items-center gap-2 text-sm'>
                <Calendar className='text-muted-foreground h-4 w-4' />
                <div>
                  <p className='font-medium'>Created</p>
                  <p className='text-muted-foreground'>
                    {format(
                      new Date(contact.attributes.created_at),
                      DATE_FORMATS.LONG,
                      { locale: enAU }
                    )}
                  </p>
                </div>
              </div>
              {contact.attributes.updated_at !==
                contact.attributes.created_at && (
                <div className='flex items-center gap-2 text-sm'>
                  <Calendar className='text-muted-foreground h-4 w-4' />
                  <div>
                    <p className='font-medium'>Last Updated</p>
                    <p className='text-muted-foreground'>
                      {format(
                        new Date(contact.attributes.updated_at),
                        DATE_FORMATS.LONG,
                        { locale: enAU }
                      )}
                    </p>
                  </div>
                </div>
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
