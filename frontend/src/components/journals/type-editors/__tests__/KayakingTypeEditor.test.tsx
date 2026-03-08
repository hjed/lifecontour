import { render, screen } from '@testing-library/react';
import { KayakingTypeEditor } from '../KayakingTypeEditor';

jest.mock('@/components/routes/RouteSelector', () => ({
  RouteSelector: () => <div data-testid='mock-route-selector' />,
}));

jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

describe('KayakingTypeEditor', () => {
  it('renders route selector and water type input in create mode', () => {
    render(<KayakingTypeEditor createMode={true} />);

    expect(screen.getByTestId('mock-route-selector')).toBeInTheDocument();
    expect(screen.getByTestId('water-type-input')).toBeInTheDocument();
  });

  it('renders view mode with kayaking summary values', () => {
    render(
      <KayakingTypeEditor
        createMode={false}
        data={{ route_id: 'route-123', water_type: 'river' }}
      />
    );

    expect(screen.getByTestId('kayaking-summary')).toBeInTheDocument();
    expect(screen.getByText(/river/i)).toBeInTheDocument();
    expect(screen.getByText('route-123')).toBeInTheDocument();
  });
});
