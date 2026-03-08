import { fireEvent, render, screen } from '@testing-library/react';
import { CanyoningTypeEditor } from '../CanyoningTypeEditor';

jest.mock('@/components/routes/RouteSelector', () => ({
  RouteSelector: ({ id }: { id?: string }) => (
    <div data-testid='mock-route-selector' data-route-selector-id={id} />
  ),
}));

jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

describe('CanyoningTypeEditor', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders route, grade, gauge fields, and flags in create mode', () => {
    render(<CanyoningTypeEditor createMode={true} />);

    expect(screen.getByTestId('mock-route-selector')).toBeInTheDocument();
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
          route_id: 'route-123',
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
    expect(screen.getByText('route-123')).toBeInTheDocument();
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
