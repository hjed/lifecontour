import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouteSelector } from '../RouteSelector';
import * as routesApi from '@/lib/api/routes';

// Mock the API hooks
jest.mock('@/lib/api/routes', () => ({
  useRoutes: jest.fn(),
}));

describe('RouteSelector Component', () => {
  const mockOnChange = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    globalThis.HTMLElement.prototype.scrollIntoView = jest.fn();
    globalThis.HTMLElement.prototype.hasPointerCapture = jest.fn();
    globalThis.HTMLElement.prototype.releasePointerCapture = jest.fn();
  });

  const setupMockRoutes = (routes: any[] = [], isLoading = false) => {
    (routesApi.useRoutes as jest.Mock).mockReturnValue({
      data: { data: routes },
      isLoading,
    });
  };

  it('renders with placeholder when no value is provided', () => {
    setupMockRoutes();
    render(<RouteSelector onChange={mockOnChange} />);

    expect(screen.getByRole('combobox')).toHaveTextContent('Select a route...');
  });

  it('renders with selected route name when value is provided and found in results', () => {
    const mockRoutes = [
      { id: '1', attributes: { name: 'Test Route 1' } },
      { id: '2', attributes: { name: 'Test Route 2' } },
    ];
    setupMockRoutes(mockRoutes);

    render(<RouteSelector value='2' onChange={mockOnChange} />);

    expect(screen.getByRole('combobox')).toHaveTextContent('Test Route 2');
  });

  it('shows loading state when fetching', async () => {
    const user = userEvent.setup();
    setupMockRoutes([], true);

    render(<RouteSelector onChange={mockOnChange} />);

    // Open the popover
    await user.click(screen.getByRole('combobox'));

    expect(await screen.findByText('Loading routes...')).toBeInTheDocument();
  });

  it('shows empty state when no routes match', async () => {
    const user = userEvent.setup();
    setupMockRoutes([]);

    render(<RouteSelector onChange={mockOnChange} />);

    // Open the popover
    await user.click(screen.getByRole('combobox'));

    // cmdk Empty state only shows if there's a search query or after items have been registered and filtered out
    const searchInput = await screen.findByPlaceholderText('Search routes...');
    await user.type(searchInput, 'abc');

    expect(await screen.findByText('No routes found.')).toBeInTheDocument();
  });

  it('allows selecting a route from the list', async () => {
    const user = userEvent.setup();
    const mockRoutes = [
      { id: '1', attributes: { name: 'Test Route 1', description: 'desc 1' } },
      { id: '2', attributes: { name: 'Test Route 2' } },
    ];
    setupMockRoutes(mockRoutes);

    render(<RouteSelector onChange={mockOnChange} />);

    // Open the popover
    await user.click(screen.getByRole('combobox'));

    // Find and click the item
    const option = await screen.findByRole('option', { name: /Test Route 1/i });
    expect(option).toBeInTheDocument();

    await user.click(option);

    // Should call onChange with the id
    expect(mockOnChange).toHaveBeenCalledWith('1');
  });

  it('allows clearing the selection by clicking the already selected route', async () => {
    const user = userEvent.setup();
    const mockRoutes = [{ id: '1', attributes: { name: 'Test Route 1' } }];
    setupMockRoutes(mockRoutes);

    render(<RouteSelector value='1' onChange={mockOnChange} />);

    // Open the popover
    await user.click(screen.getByRole('combobox'));

    // Find and click the item
    const option = await screen.findByRole('option', { name: /Test Route 1/i });
    await user.click(option);

    // Should call onChange with null to clear
    expect(mockOnChange).toHaveBeenCalledWith(null);
  });

  it('calls API with search query when typed', async () => {
    const user = userEvent.setup();
    setupMockRoutes();

    render(<RouteSelector onChange={mockOnChange} />);

    // Open the popover
    await user.click(screen.getByRole('combobox'));

    // Type in search
    const searchInput = await screen.findByPlaceholderText('Search routes...');
    await user.type(searchInput, 'mountain');

    // Let debounce settle (300ms)
    await waitFor(
      () => {
        expect(routesApi.useRoutes).toHaveBeenLastCalledWith(
          { name: 'mountain', limit: 10 },
          { enabled: true }
        );
      },
      { timeout: 1000 }
    );
  });

  it('has a "Create new route" option', async () => {
    const user = userEvent.setup();
    setupMockRoutes();

    render(<RouteSelector onChange={mockOnChange} />);

    // Open the popover
    await user.click(screen.getByRole('combobox'));

    expect(await screen.findByText('Create new route...')).toBeInTheDocument();
  });
});
