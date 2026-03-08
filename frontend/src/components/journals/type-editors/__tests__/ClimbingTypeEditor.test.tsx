import { render, screen } from '@testing-library/react';
import { ClimbingTypeEditor } from '../ClimbingTypeEditor';

jest.mock('@/components/routes/RouteSelector', () => ({
  RouteSelector: () => <div data-testid='mock-route-selector' />,
}));

jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

describe('ClimbingTypeEditor', () => {
  it('renders route, climbing type, grade, and length controls in create mode', () => {
    render(<ClimbingTypeEditor createMode={true} />);

    expect(screen.getByTestId('mock-route-selector')).toBeInTheDocument();
    expect(screen.getByText(/Climbing Type/i)).toBeInTheDocument();
    expect(screen.getByTestId('climbing-grade-input')).toBeInTheDocument();
    expect(screen.getByTestId('climbing-length-input')).toBeInTheDocument();
  });

  it('renders view mode with climbing summary values', () => {
    render(
      <ClimbingTypeEditor
        createMode={false}
        data={{
          route_id: 'route-123',
          climbing_type: 'sport',
          grade: 18,
          length: 30,
        }}
      />
    );

    expect(screen.getByTestId('climbing-summary')).toBeInTheDocument();
    expect(screen.getByText(/sport/i)).toBeInTheDocument();
    expect(screen.getByText('18')).toBeInTheDocument();
    expect(screen.getByText('30 m')).toBeInTheDocument();
    expect(screen.getByText('route-123')).toBeInTheDocument();
  });
});
