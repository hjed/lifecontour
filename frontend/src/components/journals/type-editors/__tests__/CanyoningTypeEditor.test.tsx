import { act, fireEvent, render, screen } from '@testing-library/react';
import { CanyoningTypeEditor } from '../CanyoningTypeEditor';

describe('CanyoningTypeEditor', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders grade, gauge fields, and flags in create mode', () => {
    render(<CanyoningTypeEditor createMode={true} />);

    expect(screen.getByTestId('french-grade-input')).toBeInTheDocument();
    expect(screen.getByTestId('water-gauge-name-input')).toBeInTheDocument();
    expect(screen.getByTestId('water-gauge-level-input')).toBeInTheDocument();
    expect(screen.getByTestId('vertical-switch')).toBeInTheDocument();
    expect(screen.getByTestId('night-canyon-switch')).toBeInTheDocument();
    expect(screen.getByTestId('white-water-switch')).toBeInTheDocument();
  });

  it('parses and normalises a French canyon grade before emitting onChange', () => {
    const handleChange = jest.fn();
    render(<CanyoningTypeEditor createMode={true} onChange={handleChange} />);

    fireEvent.change(screen.getByTestId('french-grade-input'), {
      target: { value: 'v3a2iv**' },
    });

    expect(handleChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ french_grade: 'v3a2IV**' })
    );
  });

  it('clears stale French grade data when the current input becomes invalid', () => {
    const handleChange = jest.fn();
    render(<CanyoningTypeEditor createMode={true} onChange={handleChange} />);

    fireEvent.change(screen.getByTestId('french-grade-input'), {
      target: { value: 'v3a2iv**' },
    });
    fireEvent.change(screen.getByTestId('french-grade-input'), {
      target: { value: 'bad-grade' },
    });

    expect(handleChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ french_grade: null })
    );
    expect(screen.getByText(/use format v3a2iv\*\*/i)).toBeInTheDocument();
  });

  it('preserves gauge updates when typing', () => {
    const handleChange = jest.fn();

    render(<CanyoningTypeEditor createMode={true} onChange={handleChange} />);

    handleChange.mockClear();

    act(() => {
      fireEvent.change(screen.getByTestId('water-gauge-name-input'), {
        target: { value: 'Kowmung Gauge' },
      });
    });

    expect(handleChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        water_guage_name: 'Kowmung Gauge',
      })
    );
  });

  it('shows a validation message for invalid French canyon grades', () => {
    render(<CanyoningTypeEditor createMode={true} />);

    fireEvent.change(screen.getByTestId('french-grade-input'), {
      target: { value: 'bad-grade' },
    });

    expect(screen.getByText(/use format v3a2iv\*\*/i)).toBeInTheDocument();
  });

  it('resets local French grade input state on cancel', () => {
    render(
      <CanyoningTypeEditor
        createMode={false}
        data={{ french_grade: 'v3a2IV**' }}
      />
    );

    fireEvent.click(screen.getByTestId('edit-button'));
    fireEvent.change(screen.getByTestId('french-grade-input'), {
      target: { value: 'bad-grade' },
    });

    expect(screen.getByText(/use format v3a2iv\*\*/i)).toBeInTheDocument();
    expect(screen.getByTestId('french-grade-input')).toHaveValue('bad-grade');

    fireEvent.click(screen.getByTestId('cancel-button'));
    fireEvent.click(screen.getByTestId('edit-button'));

    expect(screen.getByTestId('french-grade-input')).toHaveValue('v3a2IV**');
    expect(
      screen.queryByText(/use format v3a2iv\*\*/i)
    ).not.toBeInTheDocument();
  });

  it('renders view mode with canyoning summary values', () => {
    render(
      <CanyoningTypeEditor
        createMode={false}
        data={{
          french_grade: 'v3a2IV**',
          water_guage_name: 'Kowmung Gauge',
          water_guage_level: 8,
          is_vertical: true,
          is_white_water: true,
        }}
      />
    );

    expect(screen.getByTestId('canyoning-summary')).toBeInTheDocument();
    expect(screen.getByText('v3a2IV**')).toBeInTheDocument();
    expect(screen.getByText(/Kowmung Gauge/i)).toBeInTheDocument();
    expect(screen.getByText(/Vertical/i)).toBeInTheDocument();
    expect(screen.getByText(/White Water/i)).toBeInTheDocument();
  });

  it('renders the empty read-only state when no canyoning data exists', () => {
    render(<CanyoningTypeEditor createMode={false} data={{}} />);

    expect(
      screen.getByText('No canyoning details provided.')
    ).toBeInTheDocument();
    expect(screen.getByTestId('edit-button')).toBeInTheDocument();
  });

  it('falls back to a default water gauge label when only a level is provided', () => {
    render(
      <CanyoningTypeEditor
        createMode={false}
        data={{
          water_guage_name: '',
          water_guage_level: 8,
        }}
      />
    );

    expect(screen.getByTestId('canyoning-summary')).toBeInTheDocument();
    expect(screen.getByText('Gauge (8)')).toBeInTheDocument();
  });

  it('resets local French grade UI state when saved data changes', () => {
    const { rerender } = render(
      <CanyoningTypeEditor
        createMode={false}
        data={{ french_grade: 'v3a2IV**' }}
      />
    );

    fireEvent.click(screen.getByTestId('edit-button'));
    fireEvent.change(screen.getByTestId('french-grade-input'), {
      target: { value: 'bad-grade' },
    });

    rerender(
      <CanyoningTypeEditor
        createMode={false}
        data={{ french_grade: 'v4a3V*' }}
      />
    );

    expect(screen.getByTestId('french-grade-input')).toHaveValue('v4a3V*');
    expect(
      screen.queryByText(/use format v3a2iv\*\*/i)
    ).not.toBeInTheDocument();
  });
});
