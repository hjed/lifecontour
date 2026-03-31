/**
 * Tests for JournalCreateForm component.
 *
 * Tests form rendering, validation, submission, and type selection.
 */

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JournalCreateForm } from '../JournalCreateForm';
import { JournalType } from '@/types/journals';

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

const renderWithClient = (ui: React.ReactElement) => {
  const testQueryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={testQueryClient}>{ui}</QueryClientProvider>
  );
};

// Mock the useCreateJournal hook
const mockMutateAsync = jest.fn();
jest.mock('@/lib/api/journals', () => ({
  useCreateJournal: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
  useJournal: () => ({
    data: undefined,
    isLoading: false,
    error: null,
  }),
}));

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

// Ensure tests don't timeout during full test suite runs, as this component
// renders many child components and can be slow in JSDOM.
jest.setTimeout(15000);

describe('JournalCreateForm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('renders all required form fields', () => {
      renderWithClient(<JournalCreateForm />);

      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/date range/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/content/i)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /create journal/i })
      ).toBeInTheDocument();
    });

    it('renders type selector checkboxes', () => {
      renderWithClient(<JournalCreateForm />);

      expect(screen.getByLabelText(/note/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/event/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/mood rating/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/plan/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/travel/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/photo album/i)).toBeInTheDocument();
    });

    it('renders cancel button', () => {
      renderWithClient(<JournalCreateForm />);

      expect(
        screen.getByRole('button', { name: /cancel/i })
      ).toBeInTheDocument();
    });
  });

  describe('Validation', () => {
    it('shows error when title is empty', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const submitButton = screen.getByRole('button', {
        name: /create journal/i,
      });
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText(/title is required/i)).toBeInTheDocument();
      });
    });

    it('allows submission with valid title and date range', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '1', type: 'journals', attributes: {} },
      });

      renderWithClient(<JournalCreateForm />);

      const titleInput = screen.getByLabelText(/title/i);
      await user.type(titleInput, 'Test Journal');

      const submitButton = screen.getByRole('button', {
        name: /create journal/i,
      });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalled();
      });
    });

    it('prevents submission when EVENT is selected but calendar ID is missing', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      await user.type(screen.getByLabelText(/title/i), 'Event Journal');
      await user.click(screen.getByLabelText(/^event$/i));

      // Do NOT fill in calendar ID

      await user.click(screen.getByRole('button', { name: /create journal/i }));

      await waitFor(() => {
        expect(
          screen.getByText(/Event requires a valid Calendar ID/i)
        ).toBeInTheDocument();
        expect(mockMutateAsync).not.toHaveBeenCalled();
      });
    });

    it('prevents submission when PHOTO_ALBUM is selected but Immich Album ID is missing', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      await user.type(screen.getByLabelText(/title/i), 'Photo Journal');
      await user.click(screen.getByLabelText(/^photo album$/i));

      // Do NOT fill in photo URL / album ID

      await user.click(screen.getByRole('button', { name: /create journal/i }));

      await waitFor(() => {
        expect(
          screen.getByText(/Photo Album requires an Immich Album ID/i)
        ).toBeInTheDocument();
        expect(mockMutateAsync).not.toHaveBeenCalled();
      });
    });
  });

  describe('Type Selection', () => {
    it('allows selecting multiple types', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const noteCheckbox = screen.getByLabelText(/^note$/i);
      const eventCheckbox = screen.getByLabelText(/^event$/i);

      await user.click(noteCheckbox);
      await user.click(eventCheckbox);

      expect(noteCheckbox).toBeChecked();
      expect(eventCheckbox).toBeChecked();
    });

    it('allows deselecting types', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const noteCheckbox = screen.getByLabelText(/^note$/i);

      await user.click(noteCheckbox);
      expect(noteCheckbox).toBeChecked();

      await user.click(noteCheckbox);
      expect(noteCheckbox).not.toBeChecked();
    });
  });

  describe('All Journal Type Options', () => {
    it('renders all 15 journal type checkboxes', () => {
      renderWithClient(<JournalCreateForm />);

      // Base types
      expect(screen.getByLabelText(/^note$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^event$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^mood rating$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^plan$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^travel$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^photo album$/i)).toBeInTheDocument();

      // Activity types
      expect(screen.getByLabelText(/^fitness$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^outdoor activity$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^bushwalking$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^jogging$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^abseiling trip$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^canyoning$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^climbing$/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/^kayaking$/i)).toBeInTheDocument();
      expect(
        screen.getByLabelText(/^cross-country skiing$/i)
      ).toBeInTheDocument();
    });
  });

  describe('Inline Editors in Create Mode', () => {
    it('shows event type editor when EVENT is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const eventCheckbox = screen.getByLabelText(/^event$/i);
      await user.click(eventCheckbox);

      expect(screen.getByTestId('event-type-editor')).toBeInTheDocument();
    });

    it('shows mood rating type editor when MOOD_RATING is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const moodCheckbox = screen.getByLabelText(/^mood rating$/i);
      await user.click(moodCheckbox);

      expect(screen.getByTestId('mood-rating-type-editor')).toBeInTheDocument();
    });

    it('shows photo album type editor when PHOTO_ALBUM is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const photoCheckbox = screen.getByLabelText(/^photo album$/i);
      await user.click(photoCheckbox);

      expect(screen.getByTestId('photo-album-type-editor')).toBeInTheDocument();
    });

    it('shows plan type editor when PLAN is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const planCheckbox = screen.getByLabelText(/^plan$/i);
      await user.click(planCheckbox);

      expect(screen.getByTestId('plan-type-editor')).toBeInTheDocument();
    });

    it('shows travel type editor when TRAVEL is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const travelCheckbox = screen.getByLabelText(/^travel$/i);
      await user.click(travelCheckbox);

      expect(screen.getByTestId('travel-type-editor')).toBeInTheDocument();
    });

    it('shows abseiling type editor when ABSEILING_TRIP is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      await user.click(screen.getByLabelText(/^abseiling trip$/i));

      expect(
        screen.getByTestId('abseiling-trip-type-editor')
      ).toBeInTheDocument();
    });

    it('shows canyoning type editor when CANYONING is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      await user.click(screen.getByLabelText(/^canyoning$/i));

      expect(screen.getByTestId('canyoning-type-editor')).toBeInTheDocument();
    });

    it('shows climbing type editor when CLIMBING is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      await user.click(screen.getByLabelText(/^climbing$/i));

      expect(screen.getByTestId('climbing-type-editor')).toBeInTheDocument();
    });

    it('shows kayaking type editor when KAYAKING is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      await user.click(screen.getByLabelText(/^kayaking$/i));

      expect(screen.getByTestId('kayaking-type-editor')).toBeInTheDocument();
    });

    it('shows cross-country skiing type editor when CROSS_COUNTRY_SKIING is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      await user.click(screen.getByLabelText(/^cross-country skiing$/i));

      expect(
        screen.getByTestId('cross-country-skiing-type-editor')
      ).toBeInTheDocument();
    });

    it('hides editor when type is deselected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const eventCheckbox = screen.getByLabelText(/^event$/i);
      await user.click(eventCheckbox);
      expect(screen.getByTestId('event-type-editor')).toBeInTheDocument();

      await user.click(eventCheckbox);
      expect(screen.queryByTestId('event-type-editor')).not.toBeInTheDocument();
    });

    it('editor inputs are enabled in create mode (no Edit button required)', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const eventCheckbox = screen.getByLabelText(/^event$/i);
      await user.click(eventCheckbox);

      const editorContainer = screen.getByTestId('event-type-editor');

      // In create mode, the calendar ID input should be enabled
      const calendarIdInput =
        within(editorContainer).getByTestId('calendar-id-input');
      expect(calendarIdInput).not.toBeDisabled();

      // In create mode, the Edit button should NOT be present
      expect(
        within(editorContainer).queryByRole('button', { name: /edit/i })
      ).not.toBeInTheDocument();
    });

    it('mood rating editor initialises with default values in create mode', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const moodCheckbox = screen.getByLabelText(/^mood rating$/i);
      await user.click(moodCheckbox);

      const moodEditor = screen.getByTestId('mood-rating-type-editor');

      // In create mode, sliders should be initialised to 5 (default value)
      const moodValueDisplay =
        within(moodEditor).getByTestId('mood-value-display');
      expect(moodValueDisplay).toHaveTextContent('5');
    });
  });

  describe('Type Dependency Information', () => {
    it('renders selected type details inside a structured panel with dependency badges', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const canyoningCheckbox = screen.getByLabelText(/^canyoning$/i);
      await user.click(canyoningCheckbox);

      const panel = screen.getByTestId('selected-type-panel-CANYONING');

      expect(
        within(panel).getByRole('heading', { name: 'Canyoning' })
      ).toBeInTheDocument();
      expect(
        within(panel).getByText(/automatically adds/i)
      ).toBeInTheDocument();
      expect(
        within(panel).getByTestId('selected-type-dependency-CANYONING-FITNESS')
      ).toHaveTextContent('Fitness');
      expect(
        within(panel).getByTestId(
          'selected-type-dependency-CANYONING-OUTDOOR_ACTIVITY'
        )
      ).toHaveTextContent('Outdoor Activity');
    });

    it('shows dependency info when CANYONING is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const canyoningCheckbox = screen.getByLabelText(/^canyoning$/i);
      await user.click(canyoningCheckbox);

      expect(screen.getAllByText(/automatically adds/i).length).toBeGreaterThan(
        0
      );
    });

    it('shows dependency info when BUSHWALKING is selected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const bushwalkingCheckbox = screen.getByLabelText(/^bushwalking$/i);
      await user.click(bushwalkingCheckbox);

      expect(screen.getAllByText(/automatically adds/i).length).toBeGreaterThan(
        0
      );
    });

    it('does not show dependency info for NOTE which has no dependencies', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const noteCheckbox = screen.getByLabelText(/^note$/i);
      await user.click(noteCheckbox);

      expect(screen.queryByText(/automatically adds/i)).not.toBeInTheDocument();
    });

    it('hides dependency info when type is deselected', async () => {
      const user = userEvent.setup();
      renderWithClient(<JournalCreateForm />);

      const canyoningCheckbox = screen.getByLabelText(/^canyoning$/i);
      await user.click(canyoningCheckbox);

      expect(
        screen.getByTestId('selected-type-panel-CANYONING')
      ).toBeInTheDocument();

      await user.click(canyoningCheckbox);
      expect(
        screen.queryByTestId('selected-type-panel-CANYONING')
      ).not.toBeInTheDocument();
    });
  });

  describe('Form Submission', () => {
    it('submits form with correct data', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '1', type: 'journals', attributes: {} },
      });

      renderWithClient(<JournalCreateForm />);

      const titleInput = screen.getByLabelText(/title/i);
      const contentInput = screen.getByLabelText(/content/i);
      const noteCheckbox = screen.getByLabelText(/^note$/i);

      await user.type(titleInput, 'Test Journal');
      await user.type(contentInput, 'Test content');
      await user.click(noteCheckbox);

      const submitButton = screen.getByRole('button', {
        name: /create journal/i,
      });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Test Journal',
            content: 'Test content',
            types: [JournalType.NOTE],
          })
        );
      });
    });

    it('includes mood data in type_data when MOOD_RATING is selected', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '1', type: 'journals', attributes: {} },
      });

      renderWithClient(<JournalCreateForm />);

      await user.type(screen.getByLabelText(/title/i), 'Mood Journal');

      const moodCheckbox = screen.getByLabelText(/^mood rating$/i);
      await user.click(moodCheckbox);

      await user.click(screen.getByRole('button', { name: /create journal/i }));

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            types: [JournalType.MOOD_RATING],
            type_data: expect.objectContaining({
              [JournalType.MOOD_RATING]: expect.any(Object),
            }),
          })
        );
      });
    });

    it('includes photo album data in type_data when PHOTO_ALBUM is selected', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '1', type: 'journals', attributes: {} },
      });

      renderWithClient(<JournalCreateForm />);

      await user.type(screen.getByLabelText(/title/i), 'Photo Journal');

      const photoCheckbox = screen.getByLabelText(/^photo album$/i);
      await user.click(photoCheckbox);

      const albumInput = screen.getByTestId('immich-album-id-input');
      await user.type(albumInput, 'album-uuid-123');

      await user.click(screen.getByRole('button', { name: /create journal/i }));

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            types: [JournalType.PHOTO_ALBUM],
            type_data: expect.objectContaining({
              [JournalType.PHOTO_ALBUM]: expect.objectContaining({
                immich_album_id: 'album-uuid-123',
              }),
            }),
          })
        );
      });
    });

    it('includes event data in type_data when EVENT is selected', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '2', type: 'journals', attributes: {} },
      });

      renderWithClient(<JournalCreateForm />);

      await user.type(screen.getByLabelText(/title/i), 'Event Journal');

      const eventCheckbox = screen.getByLabelText(/^event$/i);
      await user.click(eventCheckbox);

      const calendarIdInput = screen.getByTestId('calendar-id-input');
      await user.type(calendarIdInput, 'calendar-uuid-123');

      await user.click(screen.getByRole('button', { name: /create journal/i }));

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            types: [JournalType.EVENT],
            type_data: expect.objectContaining({
              [JournalType.EVENT]: expect.objectContaining({
                calendar_id: 'calendar-uuid-123',
              }),
            }),
          })
        );
      });
    });

    it('includes plan type_data key when PLAN is selected', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '3', type: 'journals', attributes: {} },
      });

      renderWithClient(<JournalCreateForm />);

      await user.type(screen.getByLabelText(/title/i), 'Plan Journal');

      const planCheckbox = screen.getByLabelText(/^plan$/i);
      await user.click(planCheckbox);

      // Verify the plan editor rendered (confirming type selection worked)
      expect(await screen.findByTestId('plan-type-editor')).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: /create journal/i }));

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            types: [JournalType.PLAN],
            type_data: expect.objectContaining({
              [JournalType.PLAN]: expect.objectContaining({
                // Initial empty state: the plan editor always emits documents: [] on mount
                documents: expect.any(Array),
              }),
            }),
          })
        );
      });
    });

    it('includes canyoning data in type_data when CANYONING is selected', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '4', type: 'journals', attributes: {} },
      });

      renderWithClient(<JournalCreateForm />);

      await user.type(screen.getByLabelText(/title/i), 'Canyon Journal');
      await user.click(screen.getByLabelText(/^canyoning$/i));

      await user.type(screen.getByTestId('french-grade-input'), 'v3a2iv**');
      await user.type(screen.getByTestId('water-gauge-name-input'), 'Kowmung');
      await user.type(screen.getByTestId('water-gauge-level-input'), '8');

      await user.click(screen.getByRole('button', { name: /create journal/i }));

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            types: expect.arrayContaining([JournalType.CANYONING]),
            type_data: expect.objectContaining({
              [JournalType.CANYONING]: expect.objectContaining({
                french_grade: 'v3a2IV**',
                water_guage_name: 'Kowmung',
                water_guage_level: 8,
              }),
            }),
          })
        );
      });
    });

    it('includes abseiling data in type_data when ABSEILING_TRIP is selected', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '5', type: 'journals', attributes: {} },
      });

      renderWithClient(<JournalCreateForm />);

      await user.type(screen.getByLabelText(/title/i), 'Abseil Journal');
      await user.click(screen.getByLabelText(/^abseiling trip$/i));
      await user.type(screen.getByTestId('number-of-abseils-input'), '4');
      await user.type(screen.getByTestId('total-length-input'), '120');

      await user.click(screen.getByRole('button', { name: /create journal/i }));

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            types: expect.arrayContaining([JournalType.ABSEILING_TRIP]),
            type_data: expect.objectContaining({
              [JournalType.ABSEILING_TRIP]: expect.objectContaining({
                number_of_abseils: 4,
                total_length: 120,
              }),
            }),
          })
        );
      });
    });

    it('submits the latest abseiling type_data after a same-tick edit and submit', async () => {
      const user = userEvent.setup();
      const consoleErrorSpy = jest
        .spyOn(console, 'error')
        .mockImplementation(() => undefined);
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '6', type: 'journals', attributes: {} },
      });

      try {
        renderWithClient(<JournalCreateForm />);

        await user.type(
          screen.getByLabelText(/title/i),
          'Immediate Abseil Journal'
        );
        await user.click(screen.getByLabelText(/^abseiling trip$/i));

        const numberOfAbseilsInput = screen.getByTestId(
          'number-of-abseils-input'
        );
        const totalLengthInput = screen.getByTestId('total-length-input');
        const submitButton = screen.getByRole('button', {
          name: /create journal/i,
        });

        await act(async () => {
          fireEvent.change(numberOfAbseilsInput, { target: { value: '7' } });
          fireEvent.change(totalLengthInput, { target: { value: '210' } });
          fireEvent.click(submitButton);
        });

        await waitFor(() => {
          expect(mockMutateAsync).toHaveBeenCalledWith(
            expect.objectContaining({
              types: expect.arrayContaining([JournalType.ABSEILING_TRIP]),
              type_data: expect.objectContaining({
                [JournalType.ABSEILING_TRIP]: expect.objectContaining({
                  number_of_abseils: 7,
                  total_length: 210,
                }),
              }),
            })
          );
        });

        expect(consoleErrorSpy).not.toHaveBeenCalled();
      } finally {
        consoleErrorSpy.mockRestore();
      }
    });
  });
});
