/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { JournalFilters } from '../JournalFilters';
import {
  JournalFilters as JournalFiltersType,
  JournalType,
} from '@/types/journals';

// Mock the API hooks
jest.mock('@/lib/api/journals', () => ({
  useJournalTags: jest.fn(() => ({
    data: {
      data: [
        { id: '1', name: 'Personal', color: '#FF0000' },
        { id: '2', name: 'Work', color: '#00FF00' },
      ],
    },
    isLoading: false,
  })),
  useCalendars: jest.fn(() => ({
    data: {
      data: [
        { id: '1', attributes: { name: 'Personal', color: '#FF0000' } },
        { id: '2', attributes: { name: 'Work', color: '#00FF00' } },
      ],
    },
    isLoading: false,
  })),
}));

// Mock ContactSearchCombobox
jest.mock('@/components/contacts/ContactSearchCombobox', () => ({
  ContactSearchCombobox: ({
    onSelect,
    placeholder,
  }: {
    onSelect: (id: string) => void;
    placeholder?: string;
  }) => (
    <button onClick={() => onSelect('contact-1')} data-testid='contact-search'>
      {placeholder || 'Search contacts'}
    </button>
  ),
}));

// Mock date-fns
jest.mock('date-fns', () => ({
  format: jest.fn(() => '01 Jan 2024'),
}));

jest.mock('date-fns/locale', () => ({
  enAU: {},
}));

describe('JournalFilters', () => {
  let queryClient: QueryClient;
  const mockOnFiltersChange = jest.fn();

  const renderFilters = (filters: JournalFiltersType = {}) => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });

    return render(
      <QueryClientProvider client={queryClient}>
        <JournalFilters
          filters={filters}
          onFiltersChange={mockOnFiltersChange}
        />
      </QueryClientProvider>
    );
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders all filter sections', () => {
    renderFilters();

    expect(screen.getByText('Date Range')).toBeInTheDocument();
    expect(screen.getByText('Journal Types')).toBeInTheDocument();
    expect(screen.getByText('Contact')).toBeInTheDocument();
    expect(screen.getByText('Tags')).toBeInTheDocument();
    expect(screen.getByText('Calendar')).toBeInTheDocument();
  });

  it('renders all journal type checkboxes', () => {
    renderFilters();

    expect(screen.getByLabelText('Note')).toBeInTheDocument();
    expect(screen.getByLabelText('Event')).toBeInTheDocument();
    expect(screen.getByLabelText('Mood Rating')).toBeInTheDocument();
    expect(screen.getByLabelText('Plan')).toBeInTheDocument();
    expect(screen.getByLabelText('Travel')).toBeInTheDocument();
    expect(screen.getByLabelText('Photo Album')).toBeInTheDocument();
  });

  it('toggles journal type filter', async () => {
    const user = userEvent.setup();
    renderFilters();

    const noteCheckbox = screen.getByLabelText('Note');
    await user.click(noteCheckbox);

    expect(mockOnFiltersChange).toHaveBeenCalledWith({
      types: [JournalType.NOTE],
    });
  });

  it('handles multiple type selections', async () => {
    const user = userEvent.setup();
    renderFilters({ types: [JournalType.NOTE] });

    const eventCheckbox = screen.getByLabelText('Event');
    await user.click(eventCheckbox);

    expect(mockOnFiltersChange).toHaveBeenCalledWith({
      types: [JournalType.NOTE, JournalType.EVENT],
    });
  });

  it('removes type when unchecked', async () => {
    const user = userEvent.setup();
    renderFilters({ types: [JournalType.NOTE, JournalType.EVENT] });

    const noteCheckbox = screen.getByLabelText('Note');
    await user.click(noteCheckbox);

    expect(mockOnFiltersChange).toHaveBeenCalledWith({
      types: [JournalType.EVENT],
    });
  });

  it('renders tag checkboxes from API', () => {
    renderFilters();

    expect(screen.getByLabelText('Personal')).toBeInTheDocument();
    expect(screen.getByLabelText('Work')).toBeInTheDocument();
  });

  it('toggles tag filter', async () => {
    const user = userEvent.setup();
    renderFilters();

    const personalCheckbox = screen.getByLabelText('Personal');
    await user.click(personalCheckbox);

    expect(mockOnFiltersChange).toHaveBeenCalledWith({
      tag_ids: ['1'],
    });
  });

  it('renders a tag as checked when present in filters', () => {
    renderFilters({ tag_ids: ['1'] });

    expect(screen.getByLabelText('Personal')).toHaveAttribute(
      'aria-checked',
      'true'
    );
    expect(screen.getByLabelText('Work')).toHaveAttribute(
      'aria-checked',
      'false'
    );
  });

  it('keeps previously selected tags when a second tag is checked', async () => {
    const user = userEvent.setup();
    renderFilters({ tag_ids: ['1'] });

    await user.click(screen.getByLabelText('Work'));

    expect(mockOnFiltersChange).toHaveBeenCalledWith({
      tag_ids: ['1', '2'],
    });
  });

  it('removes only the unchecked tag', async () => {
    const user = userEvent.setup();
    renderFilters({ tag_ids: ['1', '2'] });

    await user.click(screen.getByLabelText('Personal'));

    expect(mockOnFiltersChange).toHaveBeenCalledWith({
      tag_ids: ['2'],
    });
  });

  it('renders contact search component', () => {
    renderFilters();

    // Contact search should be rendered
    const contactSearch = screen.getByTestId('contact-search');
    expect(contactSearch).toBeInTheDocument();
  });

  it('shows clear button when contact is selected', () => {
    renderFilters({ contact_id: 'contact-1' });

    expect(screen.getByText('Contact selected')).toBeInTheDocument();
    expect(screen.getByLabelText('Clear contact filter')).toBeInTheDocument();
  });

  it('clears contact filter', async () => {
    const user = userEvent.setup();
    renderFilters({ contact_id: 'contact-1' });

    const clearButton = screen.getByLabelText('Clear contact filter');
    await user.click(clearButton);

    expect(mockOnFiltersChange).toHaveBeenCalledWith({
      contact_id: undefined,
    });
  });

  it('shows clear all button when filters are active', () => {
    renderFilters({ types: [JournalType.NOTE] });

    expect(screen.getByTestId('clear-filters')).toBeInTheDocument();
  });

  it('clears all filters', async () => {
    const user = userEvent.setup();
    renderFilters({
      types: [JournalType.NOTE],
      tag_ids: ['1'],
      contact_id: 'contact-1',
    });

    const clearButton = screen.getByTestId('clear-filters');
    await user.click(clearButton);

    expect(mockOnFiltersChange).toHaveBeenCalledWith({});
  });
});
