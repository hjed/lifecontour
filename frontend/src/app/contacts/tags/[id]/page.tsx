/**
 * Contact tag page showing contacts filtered by a specific tag.
 *
 * Displays contacts that have been tagged with a specific tag,
 * with the same functionality as the main contacts page but filtered.
 * Groups and tags are the same concept in this system.
 */

'use client';

import { useMemo } from 'react';
import { useParams } from 'next/navigation';
import { Users, Tag, AlertCircle } from 'lucide-react';
import Link from 'next/link';
import { useContacts, useTags } from '@/lib/api/contacts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { FavouriteToggle } from '@/components/contacts/FavouriteToggle';

export default function ContactGroupPage() {
  return (
    <AuthGuard>
      <ContactGroupPageContent />
    </AuthGuard>
  );
}

function ContactGroupPageContent() {
  const params = useParams();
  const tagId = params.id as string;

  // Fetch all tags to find the current tag name
  const {
    data: tagsData,
    isLoading: tagsLoading,
    error: tagsError,
  } = useTags();

  // Fetch contacts filtered by this tag
  const {
    data: contactsData,
    isLoading: contactsLoading,
    error: contactsError,
  } = useContacts({
    tags: [tagId],
  });

  // Find the current tag
  const currentTag = useMemo(() => {
    if (!tagsData?.data) return null;
    return tagsData.data.find(tag => tag.id === tagId);
  }, [tagsData?.data, tagId]);

  const displayContacts = useMemo(() => {
    const contacts = contactsData?.data || [];
    return contacts.map(contact => ({
      id: contact.id,
      name: `${contact.attributes.first_name} ${contact.attributes.last_name || ''}`.trim(),
      is_favourite: contact.attributes.is_favourite || false,
      primary_email: contact.attributes.contact_methods?.find(
        m => m.attributes.method_type === 'email' && m.attributes.is_primary
      )?.attributes.value,
      primary_phone: contact.attributes.contact_methods?.find(
        m => m.attributes.method_type === 'phone' && m.attributes.is_primary
      )?.attributes.value,
      tags: contact.relationships?.tags?.data || [],
      created_at: contact.attributes.created_at,
      updated_at: contact.attributes.updated_at,
    }));
  }, [contactsData?.data]);

  if (contactsError || tagsError) {
    return (
      <div className='container mx-auto px-4 py-8'>
        <Alert variant='destructive'>
          <AlertCircle className='h-4 w-4' />
          <AlertDescription>
            {contactsError instanceof Error
              ? contactsError.message
              : tagsError instanceof Error
                ? tagsError.message
                : 'Failed to load tag or contacts'}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  // Show loading state
  if (tagsLoading || contactsLoading) {
    return (
      <div className='space-y-6'>
        <div className='mb-6'>
          <Skeleton className='mb-2 h-9 w-64' />
          <Skeleton className='h-5 w-48' />
        </div>
        <div className='grid gap-4 md:grid-cols-2 lg:grid-cols-3'>
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className='h-6 w-3/4' />
                <Skeleton className='h-4 w-1/2' />
              </CardHeader>
              <CardContent>
                <div className='space-y-2'>
                  <Skeleton className='h-4 w-full' />
                  <Skeleton className='h-4 w-2/3' />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  // Handle tag not found
  if (!currentTag) {
    return (
      <div className='space-y-6'>
        <div className='mb-6'>
          <h1 className='text-3xl font-bold tracking-tight'>Tag Not Found</h1>
          <p className='text-muted-foreground'>
            The requested tag could not be found.
          </p>
        </div>
        <Card>
          <CardContent className='pt-6'>
            <div className='py-8 text-center'>
              <AlertCircle className='text-muted-foreground mx-auto mb-4 h-12 w-12' />
              <h3 className='mb-2 text-lg font-semibold'>Tag Not Found</h3>
              <p className='text-muted-foreground mb-4'>
                The tag you&apos;re looking for doesn&apos;t exist or may have
                been deleted.
              </p>
              <Button asChild>
                <Link href='/contacts'>
                  <Users className='mr-2 h-4 w-4' />
                  Browse All Contacts
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className='space-y-6'>
      {/* Header */}
      <div className='mb-6'>
        <h1 className='flex items-center gap-2 text-3xl font-bold tracking-tight'>
          <Tag
            className='h-8 w-8'
            style={{ color: currentTag.attributes.color }}
          />
          {currentTag.attributes.name} Contacts
        </h1>
        <p className='text-muted-foreground'>
          Contacts tagged with &quot;{currentTag.attributes.name}&quot;
        </p>
      </div>

      {/* Contact List */}
      {displayContacts.length === 0 ? (
        <Card>
          <CardContent className='pt-6'>
            <div className='py-8 text-center'>
              <Tag className='text-muted-foreground mx-auto mb-4 h-12 w-12' />
              <h3 className='mb-2 text-lg font-semibold'>
                No contacts found in this tag
              </h3>
              <p className='text-muted-foreground mb-4'>
                Add some contacts to the &quot;{currentTag.attributes.name}
                &quot; tag to see them here
              </p>
              <Button asChild>
                <Link href='/contacts'>
                  <Users className='mr-2 h-4 w-4' />
                  Browse All Contacts
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className='grid gap-4 md:grid-cols-2 lg:grid-cols-3'>
          {displayContacts.map(contact => (
            <Card
              key={contact.id}
              className='transition-shadow hover:shadow-md'
            >
              <CardHeader>
                <div className='flex items-start justify-between'>
                  <CardTitle className='flex-1 text-lg'>
                    <Link
                      href={`/contacts/${contact.id}`}
                      className='hover:text-primary transition-colors'
                    >
                      {contact.name}
                    </Link>
                  </CardTitle>
                  <FavouriteToggle
                    contactId={contact.id}
                    isFavourite={contact.is_favourite}
                    contactName={contact.name}
                    size='sm'
                    className='ml-2 flex-shrink-0'
                  />
                </div>
              </CardHeader>
              <CardContent>
                <div className='space-y-2'>
                  {contact.primary_email && (
                    <p className='text-sm'>
                      <span className='font-medium'>Email:</span>{' '}
                      {contact.primary_email}
                    </p>
                  )}
                  {contact.primary_phone && (
                    <p className='text-sm'>
                      <span className='font-medium'>Phone:</span>{' '}
                      {contact.primary_phone}
                    </p>
                  )}
                  {contact.tags.length > 0 && (
                    <div className='mt-2 flex flex-wrap gap-1'>
                      {contact.tags.slice(0, 3).map(tag => (
                        <Badge
                          key={tag.id}
                          variant='secondary'
                          className='text-xs'
                        >
                          {tag.attributes.name}
                        </Badge>
                      ))}
                      {contact.tags.length > 3 && (
                        <Badge variant='outline' className='text-xs'>
                          +{contact.tags.length - 3} more
                        </Badge>
                      )}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
