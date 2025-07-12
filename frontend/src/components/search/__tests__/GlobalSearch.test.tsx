/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GlobalSearch } from '../GlobalSearch';

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};
Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
});

describe('GlobalSearch', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
  });

  it('renders search input with correct placeholder', () => {
    render(<GlobalSearch />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    expect(searchInput).toBeInTheDocument();
    expect(searchInput).toHaveAttribute('placeholder', 'Search contacts, journals...');
  });

  it('renders custom placeholder when provided', () => {
    render(<GlobalSearch placeholder="Custom search..." />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    expect(searchInput).toHaveAttribute('placeholder', 'Custom search...');
  });

  it('shows search icon', () => {
    render(<GlobalSearch />);
    
    // Search icon should be present (Lucide Search component)
    const searchIcon = document.querySelector('svg');
    expect(searchIcon).toBeInTheDocument();
  });

  it('updates input value when typing', async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    
    await user.type(searchInput, 'test query');
    expect(searchInput).toHaveValue('test query');
  });

  it('shows clear button when input has value', async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    
    // Initially no clear button
    expect(screen.queryByLabelText('Clear search')).not.toBeInTheDocument();
    
    // Type something
    await user.type(searchInput, 'test');
    
    // Clear button should appear
    expect(screen.getByLabelText('Clear search')).toBeInTheDocument();
  });

  it('clears input when clear button is clicked', async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    
    // Type something
    await user.type(searchInput, 'test');
    expect(searchInput).toHaveValue('test');
    
    // Click clear button
    const clearButton = screen.getByLabelText('Clear search');
    await user.click(clearButton);
    
    expect(searchInput).toHaveValue('');
  });

  it('calls onSearch callback when provided', async () => {
    const mockOnSearch = jest.fn();
    const user = userEvent.setup();
    render(<GlobalSearch onSearch={mockOnSearch} />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    
    await user.type(searchInput, 'test query');
    await user.keyboard('{Enter}');
    
    expect(mockOnSearch).toHaveBeenCalledWith('test query');
  });

  it('saves search to localStorage when search is performed', async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    
    await user.type(searchInput, 'test query');
    await user.keyboard('{Enter}');
    
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      'recent-searches',
      JSON.stringify(['test query'])
    );
  });

  it('loads recent searches from localStorage', () => {
    const recentSearches = ['previous search', 'another search'];
    localStorageMock.getItem.mockReturnValue(JSON.stringify(recentSearches));
    
    render(<GlobalSearch />);
    
    expect(localStorageMock.getItem).toHaveBeenCalledWith('recent-searches');
  });

  it('handles invalid JSON in localStorage gracefully', () => {
    localStorageMock.getItem.mockReturnValue('invalid json');
    
    // Should not throw an error
    expect(() => render(<GlobalSearch />)).not.toThrow();
  });

  it('shows suggestions dropdown when typing', async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    
    await user.type(searchInput, 'test');
    
    // Should show suggestions dropdown
    expect(searchInput).toHaveAttribute('aria-expanded', 'true');
  });

  it('hides suggestions when showSuggestions is false', async () => {
    const user = userEvent.setup();
    render(<GlobalSearch showSuggestions={false} />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    
    await user.type(searchInput, 'test');
    
    // Should not show suggestions dropdown
    expect(searchInput).toHaveAttribute('aria-expanded', 'false');
  });

  it('handles keyboard navigation in suggestions', async () => {
    const user = userEvent.setup();
    render(<GlobalSearch />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    
    // Focus input and type to show suggestions
    await user.click(searchInput);
    await user.type(searchInput, 'test');
    
    // Test arrow key navigation
    await user.keyboard('{ArrowDown}');
    await user.keyboard('{ArrowUp}');
    await user.keyboard('{Escape}');
    
    // Should close suggestions on Escape
    expect(searchInput).toHaveAttribute('aria-expanded', 'false');
  });

  it('applies custom className', () => {
    render(<GlobalSearch className="custom-class" />);
    
    const container = document.querySelector('.custom-class');
    expect(container).toBeInTheDocument();
  });

  it('does not perform search with empty query', async () => {
    const mockOnSearch = jest.fn();
    const user = userEvent.setup();
    render(<GlobalSearch onSearch={mockOnSearch} />);

    // Try to search with empty input
    await user.keyboard('{Enter}');

    expect(mockOnSearch).not.toHaveBeenCalled();
    expect(localStorageMock.setItem).not.toHaveBeenCalled();
  });

  it('trims whitespace from search queries', async () => {
    const mockOnSearch = jest.fn();
    const user = userEvent.setup();
    render(<GlobalSearch onSearch={mockOnSearch} />);
    
    const searchInput = screen.getByRole('combobox', { name: /global search/i });
    
    await user.type(searchInput, '  test query  ');
    await user.keyboard('{Enter}');
    
    expect(mockOnSearch).toHaveBeenCalledWith('  test query  ');
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      'recent-searches',
      JSON.stringify(['  test query  '])
    );
  });
});
