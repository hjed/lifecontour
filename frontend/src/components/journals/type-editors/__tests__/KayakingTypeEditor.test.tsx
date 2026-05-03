import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { KayakingTypeEditor } from '../KayakingTypeEditor';
import userEvent from '@testing-library/user-event';

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

describe('KayakingTypeEditor', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders water type and white water checkbox in create mode', () => {
    const queryClient = createTestQueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <KayakingTypeEditor createMode={true} />
      </QueryClientProvider>
    );

    expect(screen.getByTestId('water-type-input')).toBeInTheDocument();
    expect(screen.getByTestId('is-white-water-input')).toBeInTheDocument();
    expect(screen.queryByTestId('rapids-grade-input')).not.toBeInTheDocument();
  });

  it('shows rapids grade select when white water is checked', async () => {
    const queryClient = createTestQueryClient();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <KayakingTypeEditor createMode={true} />
      </QueryClientProvider>
    );

    const checkbox = screen.getByTestId('is-white-water-input');
    await user.click(checkbox);

    expect(screen.getByTestId('rapids-grade-input')).toBeInTheDocument();
  });

  it('clears rapids_grade when white water is unchecked and emits change', async () => {
    const handleChange = jest.fn();
    const queryClient = createTestQueryClient();
    const user = userEvent.setup();

    // Start with white water checked and a grade selected
    render(
      <QueryClientProvider client={queryClient}>
        <KayakingTypeEditor
          createMode={true}
          onChange={handleChange}
          data={{ is_white_water: true, rapids_grade: 'III' }}
        />
      </QueryClientProvider>
    );

    expect(screen.getByTestId('rapids-grade-input')).toBeInTheDocument();

    const checkbox = screen.getByTestId('is-white-water-input');
    await user.click(checkbox);

    expect(screen.queryByTestId('rapids-grade-input')).not.toBeInTheDocument();

    expect(handleChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ is_white_water: false, rapids_grade: null })
    );
  });

  it('emits changes when water type is edited', async () => {
    const handleChange = jest.fn();
    const queryClient = createTestQueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <KayakingTypeEditor createMode={true} onChange={handleChange} />
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByTestId('water-type-input'), {
      target: { value: 'sea' },
    });

    expect(handleChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ water_type: 'sea' })
    );
  });
});
