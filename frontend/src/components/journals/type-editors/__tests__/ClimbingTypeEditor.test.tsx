import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ClimbingTypeEditor } from '../ClimbingTypeEditor';

jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

describe('ClimbingTypeEditor', () => {
  it('does not render its own template selector', () => {
    // Template selection is consolidated on the abseiling block; the climbing
    // editor no longer offers a selector of its own.
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <ClimbingTypeEditor createMode={true} />
      </QueryClientProvider>
    );

    expect(screen.queryByText('Template')).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/template/i)).not.toBeInTheDocument();
  });

  it('reports indoor via onChange when the indoor toggle is switched on in create mode', async () => {
    const user = userEvent.setup();
    const onChange = jest.fn();

    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <ClimbingTypeEditor createMode={true} onChange={onChange} />
      </QueryClientProvider>
    );

    const toggle = screen.getByTestId('climbing-indoor-toggle');
    expect(toggle).not.toBeChecked();

    await user.click(toggle);

    await waitFor(() => {
      expect(onChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ indoor: true })
      );
    });
  });

  it('shows the indoor toggle as on when existing climbing data is indoor', () => {
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <ClimbingTypeEditor createMode={true} data={{ indoor: true }} />
      </QueryClientProvider>
    );

    expect(screen.getByTestId('climbing-indoor-toggle')).toBeChecked();
  });

  it('lists Indoor in the summary when the climb is indoor', () => {
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <ClimbingTypeEditor data={{ climbing_type: 'sport', indoor: true }} />
      </QueryClientProvider>
    );

    expect(screen.getByText('Indoor')).toBeInTheDocument();
  });
});
