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

  it('shows a validation message for invalid French canyon grades', () => {
    render(<CanyoningTypeEditor createMode={true} />);

    fireEvent.change(screen.getByTestId('french-grade-input'), {
      target: { value: 'bad-grade' },
    });

    expect(screen.getByText(/use format v3a2iv\*\*/i)).toBeInTheDocument();
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
});
