import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CavingTypeEditor } from '../CavingTypeEditor';

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

describe('CavingTypeEditor', () => {
  it('renders vertical and horizontal switches in create mode', () => {
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <CavingTypeEditor createMode={true} />
      </QueryClientProvider>
    );

    expect(screen.getByTestId('vertical-switch')).toBeInTheDocument();
    expect(screen.getByTestId('horizontal-switch')).toBeInTheDocument();
  });

  it('does not render its own template selector', () => {
    // Template selection is consolidated on the abseiling block; the caving
    // editor no longer offers a selector of its own.
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <CavingTypeEditor createMode={true} />
      </QueryClientProvider>
    );

    expect(screen.queryByText('Template')).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/template/i)).not.toBeInTheDocument();
  });
});
