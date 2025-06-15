/**
 * Contact creation page.
 *
 * Provides a form for creating new contacts with comprehensive
 * validation and error handling.
 */

'use client';

import { ArrowLeft } from 'lucide-react';

import { useCreateContact } from '@/lib/api/contacts';
import { ContactFormData } from '@/types/contacts';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ContactForm } from '@/components/contacts/ContactForm';
import { AuthGuard } from '@/components/auth/AuthGuard';

export default function NewContactPage() {
  return (
    <AuthGuard>
      <NewContactPageContent />
    </AuthGuard>
  );
}

function NewContactPageContent() {
  const createContactMutation = useCreateContact();

  const handleSubmit = async (data: ContactFormData) => {
    try {
      const result = await createContactMutation.mutateAsync(data);
      // Navigate to the created contact's detail page
      window.location.href = `/contacts/${result.data.id}`;
    } catch (error) {
      // Error is handled by the mutation
      console.error('Failed to create contact:', error);
    }
  };

  const handleCancel = () => {
    window.location.href = '/contacts';
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

      {/* Page Title */}
      <div className='mb-8'>
        <h1 className='text-3xl font-bold tracking-tight'>Add New Contact</h1>
        <p className='text-muted-foreground'>
          Create a new contact with their information and details
        </p>
      </div>

      {/* Contact Form */}
      <Card>
        <CardHeader>
          <CardTitle>Contact Information</CardTitle>
        </CardHeader>
        <CardContent>
          <ContactForm
            onSubmit={handleSubmit}
            onCancel={handleCancel}
            isLoading={createContactMutation.isPending}
          />
        </CardContent>
      </Card>
    </div>
  );
}
