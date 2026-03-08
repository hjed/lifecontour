import { render, screen } from '@testing-library/react';
import { CrossCountrySkiingTypeEditor } from '../CrossCountrySkiingTypeEditor';

jest.mock('@/components/routes/RouteSelector', () => ({
  RouteSelector: () => <div data-testid='mock-route-selector' />,
}));

jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

describe('CrossCountrySkiingTypeEditor', () => {
  it('renders route selector and snow conditions textarea in create mode', () => {
    render(<CrossCountrySkiingTypeEditor createMode={true} />);

    expect(screen.getByTestId('mock-route-selector')).toBeInTheDocument();
    expect(screen.getByTestId('snow-conditions-input')).toBeInTheDocument();
  });

  it('renders view mode with skiing summary values', () => {
    render(
      <CrossCountrySkiingTypeEditor
        createMode={false}
        data={{ route_id: 'route-123', snow_conditions: 'Fresh powder' }}
      />
    );

    expect(
      screen.getByTestId('cross-country-skiing-summary')
    ).toBeInTheDocument();
    expect(screen.getByText(/Fresh powder/i)).toBeInTheDocument();
    expect(screen.getByText('route-123')).toBeInTheDocument();
  });
});
