import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { FitnessTypeEditor } from '../FitnessTypeEditor';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Create a fresh QueryClient per test to avoid cache leakage between tests
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = makeQueryClient();
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('FitnessTypeEditor', () => {
  const mockOnSave = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders read-only view when journal exists and is not in edit mode', () => {
    const data = { distance: 5000, duration: 1800 };
    render(
      <FitnessTypeEditor journalId='test-1' data={data} onSave={mockOnSave} />,
      { wrapper }
    );

    // Should render ActivityStats
    expect(screen.getByTestId('activity-stats-grid')).toBeInTheDocument();
    expect(screen.getByTestId('stat-distance')).toHaveTextContent('5.00 km');

    // Inputs should not be present
    expect(screen.queryByTestId('distance-input')).not.toBeInTheDocument();
  });

  it('enters edit mode and allows updating stats', async () => {
    const data = { distance: 5000 };
    render(
      <FitnessTypeEditor journalId='test-1' data={data} onSave={mockOnSave} />,
      { wrapper }
    );

    // Switch to edit mode
    fireEvent.click(screen.getByTestId('edit-button'));

    // Edit view should now be active
    const distanceInput = screen.getByTestId(
      'distance-input'
    ) as HTMLInputElement;
    expect(distanceInput.value).toBe('5000');

    // Make an edit
    fireEvent.change(distanceInput, { target: { value: '6000' } });

    // Save
    fireEvent.click(screen.getByTestId('save-button'));

    await waitFor(() => {
      expect(mockOnSave).toHaveBeenCalledWith(
        expect.objectContaining({
          distance: 6000,
        })
      );
    });
  });

  it('renders correctly in create mode', () => {
    // createMode is when journalId is undefined and createMode prop is true
    render(
      <FitnessTypeEditor data={{}} onSave={mockOnSave} createMode={true} />,
      { wrapper }
    );

    // Should immediately show inputs and NOT the stats view
    expect(screen.getByTestId('distance-input')).toBeInTheDocument();
    expect(screen.queryByTestId('activity-stats-grid')).not.toBeInTheDocument();

    // Should show GPX upload since it's createMode
    expect(screen.getByTestId('gpx-multi-file-input')).toBeInTheDocument();
  });
});
