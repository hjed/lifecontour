/**
 * Contact creation page.
 *
 * Provides an interface equivalent to a blank contact detail page
 * that can be edited to create a new contact.
 */

'use client';

import { useState } from 'react';
import { ArrowLeft, Save } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { useCreateContact } from '@/lib/api/contacts';
import { ContactFormData } from '@/types/contacts';

export default function NewContactPage() {
  return (
    <AuthGuard>
      <NewContactPageContent />
    </AuthGuard>
  );
}

function NewContactPageContent() {
  const router = useRouter();
  const createContactMutation = useCreateContact();

  // State for the new contact being created
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [middleName, setMiddleName] = useState('');
  const [nickName, setNickName] = useState('');

  const handleSave = async () => {
    if (!firstName.trim()) {
      return; // First name is required
    }

    const contactData: ContactFormData = {
      first_name: firstName.trim(),
      last_name: lastName.trim(),
      middle_name: middleName.trim(),
      nick_name: nickName.trim(),
      contact_methods: [],
      addresses: [],
      notes: [],
    };

    try {
      const result = await createContactMutation.mutateAsync(contactData);
      router.push(`/contacts/${result.data.id}`);
    } catch (error) {
      console.error('Failed to create contact:', error);
    }
  };

  const handleCancel = () => {
    router.push('/contacts');
  };

  const canSave = firstName.trim().length > 0;

  return (
    <div className='container mx-auto px-4 py-8'>
      {/* Header */}
      <div className='mb-6 flex items-center justify-between'>
        <div className='flex items-center gap-4'>
          <Button
            variant='ghost'
            size='sm'
            onClick={handleCancel}
            disabled={createContactMutation.isPending}
          >
            <ArrowLeft className='mr-2 h-4 w-4' />
            Back to Contacts
          </Button>
        </div>
        <div className='flex gap-2'>
          <Button
            variant='outline'
            onClick={handleCancel}
            disabled={createContactMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={!canSave || createContactMutation.isPending}
            data-testid='save-contact-button'
          >
            <Save className='mr-2 h-4 w-4' />
            {createContactMutation.isPending ? 'Saving...' : 'Save Contact'}
          </Button>
        </div>
      </div>

      {/* Page Title */}
      <div className='mb-6'>
        <h1 className='text-3xl font-bold tracking-tight'>Add New Contact</h1>
        <p className='text-muted-foreground'>
          Fill in the contact details below
        </p>
      </div>

      {/* Contact Header - Same layout as detail view */}
      <header className='mb-6 grid grid-cols-1 items-start gap-x-6 gap-y-4 md:grid-cols-[128px,1fr]'>
        {/* Column 1: Avatar */}
        <div className='col-start-1'>
          <ContactAvatar
            firstName={firstName || 'New'}
            lastName={lastName || 'Contact'}
            size='lg'
            className='h-32 w-32'
          />
        </div>

        {/* Column 2: Name Fields */}
        <div className='col-start-1 space-y-3 md:col-start-2'>
          <Card>
            <CardHeader>
              <CardTitle className='text-base font-medium'>
                Contact Name
              </CardTitle>
            </CardHeader>
            <CardContent className='space-y-4'>
              <div className='grid gap-4 md:grid-cols-2'>
                <div className='space-y-2'>
                  <Label htmlFor='first-name'>
                    First Name <span className='text-destructive'>*</span>
                  </Label>
                  <Input
                    id='first-name'
                    type='text'
                    value={firstName}
                    onChange={e => setFirstName(e.target.value)}
                    placeholder='Enter first name'
                    data-testid='first-name-input'
                  />
                </div>
                <div className='space-y-2'>
                  <Label htmlFor='last-name'>Last Name</Label>
                  <Input
                    id='last-name'
                    type='text'
                    value={lastName}
                    onChange={e => setLastName(e.target.value)}
                    placeholder='Enter last name'
                    data-testid='last-name-input'
                  />
                </div>
              </div>
              <div className='grid gap-4 md:grid-cols-2'>
                <div className='space-y-2'>
                  <Label htmlFor='middle-name'>Middle Name</Label>
                  <Input
                    id='middle-name'
                    type='text'
                    value={middleName}
                    onChange={e => setMiddleName(e.target.value)}
                    placeholder='Enter middle name'
                    data-testid='middle-name-input'
                  />
                </div>
                <div className='space-y-2'>
                  <Label htmlFor='nickname'>Nickname</Label>
                  <Input
                    id='nickname'
                    type='text'
                    value={nickName}
                    onChange={e => setNickName(e.target.value)}
                    placeholder='Enter nickname'
                    data-testid='nickname-input'
                  />
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </header>

      {/* Help Text */}
      <Card>
        <CardContent className='py-6'>
          <p className='text-muted-foreground text-sm'>
            After creating the contact, you can add contact methods (email,
            phone), addresses, and other details on the contact detail page.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
