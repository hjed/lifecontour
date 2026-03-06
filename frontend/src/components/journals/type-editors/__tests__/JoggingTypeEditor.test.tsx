import { render, screen, fireEvent } from '@testing-library/react';
import { JoggingTypeEditor } from '../JoggingTypeEditor';

jest.mock('@/components/routes/RouteSelector', () => ({
  RouteSelector: () => <div data-testid='mock-route-selector' />,
}));

describe('JoggingTypeEditor', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders pace and route selector in create mode', () => {
    render(<JoggingTypeEditor createMode={true} />);

    expect(screen.getByTestId('pace-input')).toBeInTheDocument();
    expect(screen.getByTestId('mock-route-selector')).toBeInTheDocument();
  });

  it('formats initial pace correctly from seconds', () => {
    // 330 seconds = 5:30
    render(<JoggingTypeEditor createMode={true} data={{ pace: 330 }} />);

    expect(screen.getByTestId('pace-input')).toHaveValue('5:30');
  });

  it('parses mm:ss input to seconds and calls onChange', () => {
    const handleChange = jest.fn();

    render(<JoggingTypeEditor createMode={true} onChange={handleChange} />);

    const input = screen.getByTestId('pace-input');
    fireEvent.change(input, { target: { value: '6:15' } });

    // 6 * 60 + 15 = 375
    expect(handleChange).toHaveBeenCalledWith(
      expect.objectContaining({ pace: 375 })
    );
  });

  it('renders view mode with formatted pace', () => {
    render(
      <JoggingTypeEditor
        createMode={false}
        data={{ pace: 330, route_id: 'r123' }}
      />
    );

    expect(screen.getByText('5:30 /km')).toBeInTheDocument();
    expect(screen.getByText('r123')).toBeInTheDocument();
  });
});
