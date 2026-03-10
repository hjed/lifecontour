/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ContactSearchCombobox } from '../ContactSearchCombobox';
import { ContactListResponse } from '@/types/contacts';

// Mock the API
const mockFetch = jest.fn();
globalThis.fetch = mockFetch;

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    error: jest.fn(),
  },
}));

// Test data
const mockContacts: ContactListResponse = {
  data: [
    {
      type: 'contacts',
      id: '1',
      attributes: {
        first_name: 'John',
        last_name: 'Doe',
        nick_name: undefined,
        is_favourite: false,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        contact_methods: [],
        addresses: [],
        notes: [],
        relationships: [],
      },
    },
    {
      type: 'contacts',
      id: '2',
      attributes: {
        first_name: 'Jane',
        last_name: 'Smith',
        nick_name: 'Janie',
        is_favourite: true,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        contact_methods: [],
        addresses: [],
        notes: [],
        relationships: [],
      },
    },
  ],
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = 'TestWrapper';
  return Wrapper;
};

describe('ContactSearchCombobox', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockClear();
  });

  it('renders with placeholder text', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <ContactSearchCombobox
          onSelect={jest.fn()}
          placeholder='Search contacts...'
          excludeContactId='1'
        />
      </Wrapper>
    );

    expect(screen.getByRole('combobox')).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Search contacts...')
    ).toBeInTheDocument();
  });

  it('applies a custom input id', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <ContactSearchCombobox
          onSelect={jest.fn()}
          inputId='journal-contact-search'
        />
      </Wrapper>
    );

    expect(screen.getByRole('combobox')).toHaveAttribute(
      'id',
      'journal-contact-search'
    );
  });

  it('shows loading state when searching', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();

    // Mock delayed response
    const createDelayedResponse = () => {
      return new Promise(resolve => {
        const responseHandler = () =>
          resolve({ ok: true, json: () => mockContacts });
        setTimeout(responseHandler, 100);
      });
    };

    mockFetch.mockImplementation(createDelayedResponse);

    render(
      <Wrapper>
        <ContactSearchCombobox onSelect={jest.fn()} />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');
    await user.type(input, 'John');

    // Should show loading state
    await waitFor(() => {
      expect(screen.getByText('Searching...')).toBeInTheDocument();
    });
  });

  it('displays search results', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockContacts),
    });

    render(
      <Wrapper>
        <ContactSearchCombobox onSelect={jest.fn()} />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');
    await user.type(input, 'John');

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.getByText('Jane Smith (Janie)')).toBeInTheDocument();
    });
  });

  it('excludes specified contact from results', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockContacts),
    });

    render(
      <Wrapper>
        <ContactSearchCombobox onSelect={jest.fn()} excludeContactId='1' />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');
    await user.type(input, 'John');

    await waitFor(() => {
      expect(screen.queryByText('John Doe')).not.toBeInTheDocument();
      expect(screen.getByText('Jane Smith (Janie)')).toBeInTheDocument();
    });
  });

  it('calls onSelect when contact is selected', async () => {
    const user = userEvent.setup();
    const onSelect = jest.fn();
    const Wrapper = createWrapper();

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockContacts),
    });

    render(
      <Wrapper>
        <ContactSearchCombobox onSelect={onSelect} />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');
    await user.type(input, 'John');

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument();
    });

    await user.click(screen.getByText('John Doe'));

    expect(onSelect).toHaveBeenCalledWith({
      type: 'contacts',
      id: '1',
      attributes: expect.objectContaining({
        first_name: 'John',
        last_name: 'Doe',
      }),
    });
  });

  it('shows empty state when no results found', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ data: [] }),
    });

    render(
      <Wrapper>
        <ContactSearchCombobox onSelect={jest.fn()} />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');
    await user.type(input, 'NonExistent');

    await waitFor(() => {
      expect(screen.getByText('No contacts found')).toBeInTheDocument();
    });
  });

  it('handles API errors gracefully', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();

    mockFetch.mockRejectedValue(new Error('API Error'));

    render(
      <Wrapper>
        <ContactSearchCombobox onSelect={jest.fn()} />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');
    await user.type(input, 'John');

    await waitFor(() => {
      expect(screen.getByText('Error searching contacts')).toBeInTheDocument();
    });
  });

  it('clears input when contact is selected', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockContacts),
    });

    render(
      <Wrapper>
        <ContactSearchCombobox onSelect={jest.fn()} />
      </Wrapper>
    );

    const input = screen.getByRole('combobox') as HTMLInputElement;
    await user.type(input, 'John');

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument();
    });

    await user.click(screen.getByText('John Doe'));

    expect(input.value).toBe('');
  });

  it('supports keyboard navigation', async () => {
    const user = userEvent.setup();
    const onSelect = jest.fn();
    const Wrapper = createWrapper();

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockContacts),
    });

    render(
      <Wrapper>
        <ContactSearchCombobox onSelect={onSelect} />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');
    await user.type(input, 'J');

    await waitFor(() => {
      expect(screen.getByText('John Doe')).toBeInTheDocument();
    });

    // Navigate with arrow keys and select with Enter
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{Enter}');

    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        id: '1',
        attributes: expect.objectContaining({
          first_name: 'John',
        }),
      })
    );
  });

  it('debounces search input', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockContacts),
    });

    render(
      <Wrapper>
        <ContactSearchCombobox onSelect={jest.fn()} />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');

    // Type quickly
    await user.type(input, 'J');
    await user.type(input, 'o');
    await user.type(input, 'h');
    await user.type(input, 'n');

    // Should only make one API call after debounce
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });
});
