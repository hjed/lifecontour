import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OutdoorActivityTypeEditor } from '../OutdoorActivityTypeEditor';

describe('OutdoorActivityTypeEditor', () => {
  it('renders inputs in create mode', () => {
    render(<OutdoorActivityTypeEditor createMode={true} />);

    expect(screen.getByTestId('activity-type-input')).toBeInTheDocument();
    expect(screen.getByTestId('weather-conditions-input')).toBeInTheDocument();
    expect(screen.getByTestId('role-input')).toBeInTheDocument();
    expect(screen.getByTestId('participant-notes-input')).toBeInTheDocument();
    expect(screen.getByTestId('leadership-role-switch')).toBeInTheDocument();
  });

  it('calls onChange with updated data', async () => {
    const user = userEvent.setup();
    const handleChange = jest.fn();

    render(
      <OutdoorActivityTypeEditor createMode={true} onChange={handleChange} />
    );

    const input = screen.getByTestId('activity-type-input');
    await user.type(input, 'Hiking');

    expect(handleChange).toHaveBeenCalledWith(
      expect.objectContaining({ activity_type: 'Hiking' })
    );
  });

  it('renders view mode with correct data', () => {
    render(
      <OutdoorActivityTypeEditor
        createMode={false}
        data={{
          activity_type: 'Climbing',
          role: 'Instructor',
          in_leadership_role: true,
        }}
      />
    );

    expect(screen.getByText('Climbing')).toBeInTheDocument();
    expect(screen.getByText(/Instructor/i)).toBeInTheDocument();
    expect(screen.getByText(/Leadership/i)).toBeInTheDocument();
  });
});
