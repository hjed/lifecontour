import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OutdoorActivityTypeEditor } from '../OutdoorActivityTypeEditor';

describe('OutdoorActivityTypeEditor', () => {
  it('renders inputs in create mode', () => {
    render(<OutdoorActivityTypeEditor createMode={true} />);

    expect(screen.getByTestId('weather-conditions-input')).toBeInTheDocument();
    expect(screen.getByTestId('role-input')).toBeInTheDocument();
    expect(screen.getByTestId('participant-notes-input')).toBeInTheDocument();
    expect(screen.getByTestId('leadership-role-switch')).toBeInTheDocument();
  });

  it('calls onChange with updated weather conditions', async () => {
    const user = userEvent.setup();
    const handleChange = jest.fn();

    render(
      <OutdoorActivityTypeEditor createMode={true} onChange={handleChange} />
    );

    const input = screen.getByTestId('weather-conditions-input');
    await user.type(input, 'Sunny');

    expect(handleChange).toHaveBeenCalledWith(
      expect.objectContaining({ weather_conditions: 'Sunny' })
    );
  });

  it('renders view mode with correct data', () => {
    render(
      <OutdoorActivityTypeEditor
        createMode={false}
        data={{
          weather_conditions: 'Clear, 25°C',
          role: 'Instructor',
          in_leadership_role: true,
        }}
      />
    );

    expect(screen.getByText(/Clear, 25°C/)).toBeInTheDocument();
    expect(screen.getByText(/Instructor/i)).toBeInTheDocument();
    expect(screen.getByText(/Leadership/i)).toBeInTheDocument();
  });

  it('does not render activity_type input field', () => {
    render(<OutdoorActivityTypeEditor createMode={true} />);

    expect(screen.queryByTestId('activity-type-input')).not.toBeInTheDocument();
  });
});
