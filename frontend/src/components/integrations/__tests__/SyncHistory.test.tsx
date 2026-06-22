/** @jest-environment jsdom */
import { fireEvent, render, screen } from '@testing-library/react';
import { SyncHistory } from '../SyncHistory';
import { useSyncHistory } from '@/lib/api/integrations';

// The dialog's data comes entirely from this hook; mock it so the test drives
// the rendered status badges directly.
jest.mock('@/lib/api/integrations', () => ({
  useSyncHistory: jest.fn(),
}));

function makeJob(status: string) {
  return {
    id: `job-${status}`,
    type: 'sync-job',
    attributes: {
      status,
      syncType: 'smart',
      createdAt: '2026-01-01T12:00:00Z',
      errorMessage: null,
      contactsProcessed: null,
    },
  };
}

function mockHistory(jobs: unknown[]) {
  (useSyncHistory as jest.Mock).mockReturnValue({
    data: { data: jobs },
    isLoading: false,
    error: null,
  });
}

function openDialog() {
  fireEvent.click(screen.getByRole('button', { name: /sync history/i }));
}

describe('SyncHistory status badges', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders in_progress as an active "In Progress" badge', () => {
    mockHistory([makeJob('in_progress')]);
    render(<SyncHistory integrationId='strava' />);
    openDialog();

    // The active fan-out state is announced with a human-readable label, never
    // the raw snake_case value, and is not styled as a terminal/error state.
    expect(screen.getByText('In Progress')).toBeInTheDocument();
    expect(screen.queryByText('in_progress')).not.toBeInTheDocument();
    expect(screen.queryByText('Failed')).not.toBeInTheDocument();
  });

  it('keeps existing statuses rendering correctly (no regression)', () => {
    mockHistory([makeJob('completed'), makeJob('failed')]);
    render(<SyncHistory integrationId='strava' />);
    openDialog();

    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });
});
