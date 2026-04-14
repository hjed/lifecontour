import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CalendarViewToggle, CalendarViewMode } from '../CalendarViewToggle';

describe('CalendarViewToggle', () => {
  const defaultProps = {
    value: 'list' as CalendarViewMode,
    onChange: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders all three view options', () => {
    render(<CalendarViewToggle {...defaultProps} />);

    expect(
      screen.getByRole('radio', { name: /list view/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('radio', { name: /month view/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('radio', { name: /agenda view/i })
    ).toBeInTheDocument();
  });

  it('shows list option as selected by default', () => {
    render(<CalendarViewToggle {...defaultProps} value='list' />);

    const listButton = screen.getByRole('radio', { name: /list view/i });
    expect(listButton).toHaveAttribute('aria-checked', 'true');
  });

  it('shows month option as selected when value is month', () => {
    render(<CalendarViewToggle {...defaultProps} value='month' />);

    const monthButton = screen.getByRole('radio', { name: /month view/i });
    expect(monthButton).toHaveAttribute('aria-checked', 'true');
  });

  it('calls onChange with correct value on click', async () => {
    const user = userEvent.setup();
    const onChange = jest.fn();
    render(<CalendarViewToggle {...defaultProps} onChange={onChange} />);

    await user.click(screen.getByRole('radio', { name: /month view/i }));
    expect(onChange).toHaveBeenCalledWith('month');

    await user.click(screen.getByRole('radio', { name: /agenda view/i }));
    expect(onChange).toHaveBeenCalledWith('agenda');
  });

  it('has accessible radiogroup role', () => {
    render(<CalendarViewToggle {...defaultProps} />);

    expect(
      screen.getByRole('radiogroup', { name: /view mode/i })
    ).toBeInTheDocument();
  });
});
