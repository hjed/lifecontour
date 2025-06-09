/**
 * Contacts List Page
 *
 * Main contacts management interface with search, filtering, and pagination.
 * Follows Australian localization and accessibility standards.
 */

'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/lib/auth-context';
import { apiClient } from '@/lib/api-client';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Search,
  Plus,
  Filter,
  Edit,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Users,
  AlertCircle,
} from 'lucide-react';

interface Contact {
  id: string;
  type: 'contact';
  attributes: {
    first_name: string;
    last_name: string;
    email?: string;
    phone?: string;
    company?: string;
    tags?: string[];
    created_at: string;
    updated_at: string;
  };
}

interface ContactsResponse {
  data: Contact[];
  meta: {
    total: number;
    page: number;
    limit: number;
    total_pages: number;
  };
  links: {
    self?: string;
    first?: string;
    last?: string;
    prev?: string;
    next?: string;
  };
}

export default function ContactsPage() {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchLoading, setSearchLoading] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalContacts, setTotalContacts] = useState(0);

  // Load contacts
  const loadContacts = async (page = 1, search = '') => {
    try {
      setLoading(page === 1);
      setError(null);

      const response = await apiClient.getContacts(page, 20, search);

      // Check if the response has errors
      if (response.errors && response.errors.length > 0) {
        throw new Error(
          response.errors[0].detail || 'Failed to fetch contacts'
        );
      }

      // Handle the API response format
      if (response.data) {
        // Check if response.data is an array (direct contacts) or an object (paginated response)
        if (Array.isArray(response.data)) {
          // Direct array of contacts
          setContacts(response.data);
          setCurrentPage((response.meta?.page as number) || 1);
          setTotalPages((response.meta?.total_pages as number) || 1);
          setTotalContacts(
            (response.meta?.total as number) || response.data.length
          );
        } else {
          // Paginated response structure
          const contactsData = response.data as ContactsResponse;
          setContacts(contactsData.data);
          setCurrentPage(contactsData.meta.page);
          setTotalPages(contactsData.meta.total_pages);
          setTotalContacts(contactsData.meta.total);
        }
      } else {
        // No data returned
        setContacts([]);
        setCurrentPage(1);
        setTotalPages(1);
        setTotalContacts(0);
      }
    } catch (err) {
      console.error('Failed to load contacts:', err);
      const errorMessage =
        err instanceof Error ? err.message : 'Failed to fetch contacts';
      setError(errorMessage);
      setContacts([]);
    } finally {
      setLoading(false);
    }
  };

  // Search contacts
  const searchContacts = async (query: string) => {
    try {
      setSearchLoading(true);
      setError(null);

      if (!query.trim()) {
        await loadContacts(1);
        return;
      }

      const response = await apiClient.searchContacts(query);

      // Check if the response has errors
      if (response.errors && response.errors.length > 0) {
        throw new Error(response.errors[0].detail || 'Search failed');
      }

      const searchData = response.data;

      // Convert search results to contact format
      const searchContacts =
        searchData?.hits?.map(
          (hit: {
            id: string;
            first_name: string;
            last_name: string;
            email?: string;
            phone?: string;
            company?: string;
            tags?: string[];
            created_at?: string;
            updated_at?: string;
          }) => ({
            id: hit.id,
            type: 'contact' as const,
            attributes: {
              first_name: hit.first_name,
              last_name: hit.last_name,
              email: hit.email,
              phone: hit.phone,
              company: hit.company,
              tags: hit.tags || [],
              created_at: hit.created_at || '2024-01-01T00:00:00Z',
              updated_at: hit.updated_at || '2024-01-01T00:00:00Z',
            },
          })
        ) || [];

      setContacts(searchContacts);
      setCurrentPage(1);
      setTotalPages(1);
      setTotalContacts(searchContacts.length);
    } catch (err) {
      console.error('Search failed:', err);
      setError('Search service is temporarily unavailable');
      // Don't clear contacts on search error for debugging
      // setContacts([]);
      // setCurrentPage(1);
      // setTotalPages(1);
      // setTotalContacts(0);
    } finally {
      setSearchLoading(false);
    }
  };

  // Handle search
  const handleSearch = async () => {
    await searchContacts(searchQuery);
  };

  // Clear search
  const clearSearch = async () => {
    setSearchQuery('');
    await loadContacts(1);
  };

  // Handle pagination
  const goToPage = async (page: number) => {
    if (page >= 1 && page <= totalPages) {
      await loadContacts(page, searchQuery);
    }
  };

  // Format date in Australian format
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-AU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  };

  // Load contacts on mount
  useEffect(() => {
    if (isAuthenticated && !authLoading) {
      loadContacts();
    }
  }, [isAuthenticated, authLoading]);

  // Redirect to login if not authenticated
  if (!authLoading && !isAuthenticated) {
    return null; // Auth context will handle redirect
  }

  return (
    <main className='container mx-auto space-y-6 p-4'>
      {/* Page Header */}
      <div className='flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between'>
        <div>
          <h1 className='text-3xl font-bold tracking-tight'>Contacts</h1>
          <p className='text-muted-foreground'>
            Manage your personal and professional contacts
          </p>
        </div>
        <Button data-testid='add-contact-button' className='w-full sm:w-auto'>
          <Plus className='mr-2 h-4 w-4' />
          Add Contact
        </Button>
      </div>

      {/* Search and Filters */}
      <Card>
        <CardContent className='p-4'>
          <div className='flex flex-col gap-4 sm:flex-row'>
            <div className='flex flex-1 gap-2'>
              <Input
                data-testid='contact-search-input'
                placeholder='Search contacts...'
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                aria-label='Search contacts'
                className='flex-1'
              />
              <Button
                data-testid='contact-search-button'
                onClick={handleSearch}
                disabled={searchLoading}
                variant='outline'
              >
                <Search className='h-4 w-4' />
              </Button>
              {searchQuery && (
                <Button
                  data-testid='clear-search-button'
                  onClick={clearSearch}
                  variant='outline'
                  size='sm'
                >
                  Clear
                </Button>
              )}
            </div>
            <Button
              data-testid='filter-button'
              variant='outline'
              className='w-full sm:w-auto'
            >
              <Filter className='mr-2 h-4 w-4' />
              Filters
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Error State */}
      {error && (
        <Alert variant='destructive'>
          <AlertCircle className='h-4 w-4' />
          <AlertDescription data-testid='error-message'>
            {error}
          </AlertDescription>
        </Alert>
      )}

      {/* Loading State */}
      {loading && (
        <div data-testid='contacts-loading' className='space-y-4'>
          {[...Array(5)].map((_, i) => (
            <Card key={i}>
              <CardContent className='p-4'>
                <div className='flex items-center space-x-4'>
                  <Skeleton className='h-12 w-12 rounded-full' />
                  <div className='flex-1 space-y-2'>
                    <Skeleton className='h-4 w-[200px]' />
                    <Skeleton className='h-4 w-[150px]' />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Contacts List */}
      {!loading && (
        <>
          {contacts.length === 0 ? (
            /* Empty State */
            <Card data-testid='contacts-empty-state'>
              <CardContent className='p-8 text-center'>
                <Users className='text-muted-foreground mx-auto mb-4 h-12 w-12' />
                <h3 className='mb-2 text-lg font-semibold'>
                  No contacts found
                </h3>
                <p
                  data-testid='empty-state-message'
                  className='text-muted-foreground mb-4'
                >
                  {searchQuery
                    ? `No contacts match "${searchQuery}". Try a different search term.`
                    : "No contacts found. You haven't added any contacts yet. Start building your network!"}
                </p>
                <Button data-testid='add-contact-button'>
                  <Plus className='mr-2 h-4 w-4' />
                  Add Your First Contact
                </Button>
              </CardContent>
            </Card>
          ) : (
            /* Contacts List */
            <div data-testid='contacts-list' className='space-y-4'>
              {contacts.map(contact => (
                <Card
                  key={contact.id}
                  data-testid={`contact-item-${contact.id}`}
                  role='listitem'
                >
                  <CardContent className='p-4'>
                    <div className='flex items-center justify-between'>
                      <div className='flex flex-1 items-center space-x-4'>
                        <div className='bg-primary/10 flex h-12 w-12 items-center justify-center rounded-full'>
                          <span className='text-primary text-sm font-medium'>
                            {contact.attributes.first_name[0]}
                            {contact.attributes.last_name[0]}
                          </span>
                        </div>
                        <div className='min-w-0 flex-1'>
                          <h3
                            data-testid='contact-name'
                            className='truncate font-semibold'
                          >
                            {contact.attributes.first_name}{' '}
                            {contact.attributes.last_name}
                          </h3>
                          {contact.attributes.email && (
                            <p
                              data-testid='contact-email'
                              className='text-muted-foreground truncate text-sm'
                            >
                              {contact.attributes.email}
                            </p>
                          )}
                          {contact.attributes.company && (
                            <p
                              data-testid='contact-company'
                              className='text-muted-foreground truncate text-sm'
                            >
                              {contact.attributes.company}
                            </p>
                          )}
                          <div className='mt-2 flex items-center gap-2'>
                            {contact.attributes.tags?.map(tag => (
                              <Badge
                                key={tag}
                                variant='secondary'
                                className='text-xs'
                              >
                                {tag}
                              </Badge>
                            ))}
                            <span
                              data-testid='contact-created-date'
                              className='text-muted-foreground text-xs'
                            >
                              Added {formatDate(contact.attributes.created_at)}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className='flex items-center gap-2'>
                        <Button
                          data-testid='edit-contact-button'
                          variant='outline'
                          size='sm'
                        >
                          <Edit className='h-4 w-4' />
                        </Button>
                        <Button
                          data-testid='delete-contact-button'
                          variant='outline'
                          size='sm'
                        >
                          <Trash2 className='h-4 w-4' />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <Card data-testid='pagination'>
              <CardContent className='p-4'>
                <div className='flex items-center justify-between'>
                  <p className='text-muted-foreground text-sm'>
                    Showing {(currentPage - 1) * 20 + 1} to{' '}
                    {Math.min(currentPage * 20, totalContacts)} of{' '}
                    {totalContacts} contacts
                  </p>
                  <div className='flex items-center gap-2'>
                    <Button
                      data-testid='pagination-previous'
                      variant='outline'
                      size='sm'
                      onClick={() => goToPage(currentPage - 1)}
                      disabled={currentPage === 1}
                    >
                      <ChevronLeft className='h-4 w-4' />
                      Previous
                    </Button>

                    {/* Page numbers */}
                    {[...Array(Math.min(5, totalPages))].map((_, i) => {
                      const pageNum = Math.max(1, currentPage - 2) + i;
                      if (pageNum > totalPages) return null;

                      return (
                        <Button
                          key={pageNum}
                          data-testid={`pagination-page-${pageNum}`}
                          variant={
                            pageNum === currentPage ? 'default' : 'outline'
                          }
                          size='sm'
                          onClick={() => goToPage(pageNum)}
                        >
                          {pageNum}
                        </Button>
                      );
                    })}

                    <Button
                      data-testid='pagination-next'
                      variant='outline'
                      size='sm'
                      onClick={() => goToPage(currentPage + 1)}
                      disabled={currentPage === totalPages}
                    >
                      Next
                      <ChevronRight className='h-4 w-4' />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
