import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { JournalRoutesEditor } from '../JournalRoutesEditor';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useRoutes, useCreateRoute } from '@/lib/api/routes';
import { toast } from 'sonner';

// Mock the API hooks
jest.mock('@/lib/api/routes', () => ({
  useRoutes: jest.fn(),
  useCreateRoute: jest.fn(),
}));

jest.mock('sonner', () => ({
  toast: {
    error: jest.fn(),
  },
}));

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

describe('JournalRoutesEditor', () => {
  const mockMutateAsync = jest.fn();

  beforeAll(() => {
    Object.defineProperty(File.prototype, 'text', {
      value: jest.fn().mockResolvedValue('<gpx></gpx>'),
      writable: true,
      configurable: true,
    });
  });

  beforeEach(() => {
    jest.clearAllMocks();
    (useCreateRoute as jest.Mock).mockReturnValue({
      mutateAsync: mockMutateAsync,
    });
    (useRoutes as jest.Mock).mockReturnValue({
      data: { data: [], total_count: 0 },
      isLoading: false,
    });
  });

  describe('createMode', () => {
    it('adds pending routes when a file is uploaded', async () => {
      const mockOnPendingRoutesChange = jest.fn();
      render(
        <JournalRoutesEditor
          createMode={true}
          pendingRoutes={[]}
          onPendingRoutesChange={mockOnPendingRoutesChange}
          isEditing={true}
        />,
        { wrapper }
      );

      const fileInput = screen.getByTestId('gpx-multi-file-input');
      const file = new File(['<gpx></gpx>'], 'track1.gpx', {
        type: 'application/gpx+xml',
      });
      fireEvent.change(fileInput, { target: { files: [file] } });

      await waitFor(() => {
        expect(mockOnPendingRoutesChange).toHaveBeenCalledWith([
          { name: 'track1', gpx_data: '<gpx></gpx>' },
        ]);
      });
    });

    it('removes a pending route when delete is clicked', () => {
      const mockOnPendingRoutesChange = jest.fn();
      render(
        <JournalRoutesEditor
          createMode={true}
          pendingRoutes={[{ name: 'track1', gpx_data: '<gpx></gpx>' }]}
          onPendingRoutesChange={mockOnPendingRoutesChange}
          isEditing={true}
        />,
        { wrapper }
      );

      // The remove button should be the only button rendered if there are no other tracks
      const removeButton = screen.getAllByRole('button')[0];
      fireEvent.click(removeButton);

      expect(mockOnPendingRoutesChange).toHaveBeenCalledWith([]);
    });
  });

  describe('editMode', () => {
    it('triggers mutation when a file is uploaded', async () => {
      render(
        <JournalRoutesEditor
          createMode={false}
          journalId='test-123'
          isEditing={true}
        />,
        { wrapper }
      );

      const fileInput = screen.getByTestId('gpx-multi-file-input');
      const file = new File(['<gpx></gpx>'], 'track2.gpx', {
        type: 'application/gpx+xml',
      });
      fireEvent.change(fileInput, { target: { files: [file] } });

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith({
          journalId: 'test-123',
          data: {
            name: 'track2',
            gpx_data: '<gpx></gpx>',
          },
        });
      });
    });

    it('shows error toast when mutation fails', async () => {
      mockMutateAsync.mockRejectedValueOnce(new Error('Upload failed'));
      render(
        <JournalRoutesEditor
          createMode={false}
          journalId='test-123'
          isEditing={true}
        />,
        { wrapper }
      );

      const fileInput = screen.getByTestId('gpx-multi-file-input');
      const file = new File(['<gpx></gpx>'], 'track3.gpx', {
        type: 'application/gpx+xml',
      });
      fireEvent.change(fileInput, { target: { files: [file] } });

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(
          'Failed to process 1 GPX file(s)'
        );
      });
    });
  });
});
