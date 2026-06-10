/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { CreateAlbumButton } from '../CreateAlbumButton';
import { JournalType, type Journal } from '@/types/journals';

const mockUseIntegrations = jest.fn();
const mockSearchMutate = jest.fn();
const mockUseImmichPhotoSearch = jest.fn();

jest.mock('@/lib/api/integrations', () => ({
  useIntegrations: () => mockUseIntegrations(),
}));

jest.mock('@/lib/api/immich-albums', () => ({
  useImmichPhotoSearch: () => mockUseImmichPhotoSearch(),
}));

jest.mock('sonner', () => ({
  toast: { info: jest.fn(), success: jest.fn(), error: jest.fn() },
}));

// The dialog is exercised in its own suite; stub it so this suite stays focused
// on the button's visibility + search-trigger behaviour.
jest.mock('../CreateAlbumDialog', () => ({
  CreateAlbumDialog: () => <div data-testid='create-album-dialog' />,
}));

function buildJournal(overrides: Partial<Journal> = {}): Journal {
  return {
    id: '42',
    title: 'Trip to the coast',
    content: '',
    event_date_range: {
      start: '2024-01-15T00:00:00Z',
      end: '2024-01-16T00:00:00Z',
    },
    types: [JournalType.NOTE],
    contacts: [],
    tags: [],
    children: [],
    ...overrides,
  } as Journal;
}

function connectedIntegrations() {
  return {
    data: {
      data: [
        {
          id: 'immich',
          type: 'integration',
          attributes: { status: 'connected' },
        },
      ],
    },
  };
}

describe('CreateAlbumButton', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseImmichPhotoSearch.mockReturnValue({
      mutate: mockSearchMutate,
      isPending: false,
    });
  });

  it('renders when Immich connected, date range set, and no album linked', () => {
    mockUseIntegrations.mockReturnValue(connectedIntegrations());

    render(<CreateAlbumButton journal={buildJournal()} />);

    expect(screen.getByTestId('create-album-button')).toBeInTheDocument();
  });

  it('is hidden when Immich is not connected', () => {
    mockUseIntegrations.mockReturnValue({
      data: {
        data: [
          {
            id: 'immich',
            type: 'integration',
            attributes: { status: 'disconnected' },
          },
        ],
      },
    });

    render(<CreateAlbumButton journal={buildJournal()} />);

    expect(screen.queryByTestId('create-album-button')).not.toBeInTheDocument();
  });

  it('is hidden when the journal has no event date range', () => {
    mockUseIntegrations.mockReturnValue(connectedIntegrations());

    render(
      <CreateAlbumButton
        journal={buildJournal({ event_date_range: { start: '', end: '' } })}
      />
    );

    expect(screen.queryByTestId('create-album-button')).not.toBeInTheDocument();
  });

  it('is hidden when the date range is incomplete (missing end)', () => {
    mockUseIntegrations.mockReturnValue(connectedIntegrations());

    render(
      <CreateAlbumButton
        journal={buildJournal({
          event_date_range: { start: '2024-01-15T00:00:00Z', end: '' },
        })}
      />
    );

    expect(screen.queryByTestId('create-album-button')).not.toBeInTheDocument();
  });

  it('is hidden when the journal already has a linked album', () => {
    mockUseIntegrations.mockReturnValue(connectedIntegrations());

    render(
      <CreateAlbumButton
        journal={buildJournal({
          types: [JournalType.NOTE, JournalType.PHOTO_ALBUM],
        })}
      />
    );

    expect(screen.queryByTestId('create-album-button')).not.toBeInTheDocument();
  });

  it('triggers a photo search on click', async () => {
    mockUseIntegrations.mockReturnValue(connectedIntegrations());
    const user = userEvent.setup();

    render(<CreateAlbumButton journal={buildJournal()} />);
    await user.click(screen.getByTestId('create-album-button'));

    expect(mockSearchMutate).toHaveBeenCalledWith('42', expect.any(Object));
  });

  it('shows a loading state while the search is pending', () => {
    mockUseIntegrations.mockReturnValue(connectedIntegrations());
    mockUseImmichPhotoSearch.mockReturnValue({
      mutate: mockSearchMutate,
      isPending: true,
    });

    render(<CreateAlbumButton journal={buildJournal()} />);

    const button = screen.getByTestId('create-album-button');
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
  });

  it('opens the selection dialog when the search returns photos', async () => {
    mockUseIntegrations.mockReturnValue(connectedIntegrations());
    mockSearchMutate.mockImplementation((_id, options) => {
      options.onSuccess([
        {
          id: 'asset-1',
          thumbnailUrl: '/thumb/asset-1',
          originalFileName: 'one.jpg',
          takenAt: null,
        },
      ]);
    });
    const user = userEvent.setup();

    render(<CreateAlbumButton journal={buildJournal()} />);
    await user.click(screen.getByTestId('create-album-button'));

    expect(screen.getByTestId('create-album-dialog')).toBeInTheDocument();
    expect(toast.info).not.toHaveBeenCalled();
  });

  it('shows a message instead of an empty dialog when no photos are found', async () => {
    mockUseIntegrations.mockReturnValue(connectedIntegrations());
    mockSearchMutate.mockImplementation((_id, options) => {
      options.onSuccess([]);
    });
    const user = userEvent.setup();

    render(<CreateAlbumButton journal={buildJournal()} />);
    await user.click(screen.getByTestId('create-album-button'));

    expect(screen.queryByTestId('create-album-dialog')).not.toBeInTheDocument();
    expect(toast.info).toHaveBeenCalled();
  });
});
