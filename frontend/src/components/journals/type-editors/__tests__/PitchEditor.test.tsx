import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PitchEditor } from '../PitchEditor';
import type { AbseilPitch } from '@/types/journals';

describe('PitchEditor', () => {
  const mockOnChange = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders read-only mode correctly', () => {
    const pitches: AbseilPitch[] = [
      {
        id: 1,
        pitch_number: 1,
        height: 10,
        anchor_location: 'TR',
        anchor_type: 'chains',
        did_setup: true,
        did_rescue: false,
        notes: 'A slippery descent',
      },
    ];

    render(
      <PitchEditor
        pitches={pitches}
        onChange={mockOnChange}
        isEditing={false}
      />
    );

    expect(screen.getByTestId('pitch-editor-readonly')).toBeInTheDocument();
    expect(screen.getByText('Pitches (1)')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.getByText('10m')).toBeInTheDocument();
    expect(screen.getByText('TR')).toBeInTheDocument();
    expect(screen.getByText('chains')).toBeInTheDocument();
    expect(screen.getByText('Setup')).toBeInTheDocument();
    expect(screen.queryByText('Rescue')).not.toBeInTheDocument();
    expect(screen.getByText('A slippery descent')).toBeInTheDocument();
  });

  it('renders nothing in read-only mode if there are no pitches', () => {
    const { container } = render(
      <PitchEditor pitches={[]} onChange={mockOnChange} isEditing={false} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('adds a new pitch', async () => {
    const user = userEvent.setup();
    render(
      <PitchEditor pitches={[]} onChange={mockOnChange} isEditing={true} />
    );

    expect(
      screen.getByText(
        'No pitches added. Click "Add Pitch" to record abseil details.'
      )
    ).toBeInTheDocument();

    await user.click(screen.getByTestId('add-pitch-button'));

    expect(mockOnChange).toHaveBeenCalledWith([
      {
        pitch_number: 1,
        height: null,
        anchor_location: null,
        anchor_type: null,
        did_rescue: null,
        did_setup: null,
        notes: null,
        pitch_type: null,
      },
    ]);
  });

  it('shows type badges for jump and down climb pitches in read-only mode', () => {
    const pitches: AbseilPitch[] = [
      { id: 1, pitch_number: 1, height: 20 },
      { id: 2, pitch_number: 2, height: 5, pitch_type: 'jump' },
      { id: 3, pitch_number: 3, height: 3, pitch_type: 'down_climb' },
    ];

    render(
      <PitchEditor
        pitches={pitches}
        onChange={mockOnChange}
        isEditing={false}
      />
    );

    expect(screen.getByText('Jump')).toBeInTheDocument();
    expect(screen.getByText('DC')).toBeInTheDocument();
    // Abseil pitches (null type) show no type badge.
    expect(screen.queryByText('Abseil')).not.toBeInTheDocument();
  });

  it('renders a type select per pitch row defaulting to Abseil', () => {
    const pitches: AbseilPitch[] = [
      { id: 1, pitch_number: 1 },
      { id: 2, pitch_number: 2, pitch_type: 'jump' },
    ];

    render(
      <PitchEditor pitches={pitches} onChange={mockOnChange} isEditing={true} />
    );

    const firstTypeSelect = screen.getByLabelText('Type for pitch 1');
    const secondTypeSelect = screen.getByLabelText('Type for pitch 2');
    expect(firstTypeSelect).toHaveTextContent('Abseil');
    expect(secondTypeSelect).toHaveTextContent('Jump');
  });

  it('removes a pitch', async () => {
    const user = userEvent.setup();
    const pitches: AbseilPitch[] = [
      {
        id: 1,
        pitch_number: 1,
        height: 10,
      },
      {
        id: 2,
        pitch_number: 2,
        height: 20,
      },
    ];

    render(
      <PitchEditor pitches={pitches} onChange={mockOnChange} isEditing={true} />
    );

    // Click remove on the first pitch
    await user.click(screen.getByTestId('remove-pitch-0'));

    expect(mockOnChange).toHaveBeenCalledWith([
      {
        id: 2,
        pitch_number: 2,
        height: 20,
      },
    ]);
  });

  it('updates a pitch field', async () => {
    const pitches: AbseilPitch[] = [
      {
        id: 1,
        pitch_number: 1,
        height: 10,
      },
    ];

    render(
      <PitchEditor pitches={pitches} onChange={mockOnChange} isEditing={true} />
    );

    const heightInput = screen.getByLabelText('Height for pitch 1');

    fireEvent.change(heightInput, { target: { value: '15' } });

    expect(mockOnChange).toHaveBeenCalledWith([
      {
        id: 1,
        pitch_number: 1,
        height: 15,
      },
    ]);
  });

  it('updates setup and rescue checkboxes', async () => {
    const user = userEvent.setup();
    const pitches: AbseilPitch[] = [
      {
        id: 1,
        pitch_number: 1,
        did_setup: false,
        did_rescue: false,
      },
    ];

    render(
      <PitchEditor pitches={pitches} onChange={mockOnChange} isEditing={true} />
    );

    const setupCheckbox = screen.getByTestId('pitch-setup-0');
    await user.click(setupCheckbox);

    expect(mockOnChange).toHaveBeenCalledWith([
      {
        id: 1,
        pitch_number: 1,
        did_setup: true,
        did_rescue: false,
      },
    ]);
  });

  it('updates the notes field', async () => {
    const pitches: AbseilPitch[] = [
      {
        id: 1,
        pitch_number: 1,
        notes: '',
      },
    ];

    render(
      <PitchEditor pitches={pitches} onChange={mockOnChange} isEditing={true} />
    );

    const notesInput = screen.getByLabelText('Notes for pitch 1');
    fireEvent.change(notesInput, { target: { value: 'Very wet' } });

    expect(mockOnChange).toHaveBeenCalledWith([
      {
        id: 1,
        pitch_number: 1,
        notes: 'Very wet',
      },
    ]);
  });
});
