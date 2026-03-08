import { render, screen } from '@testing-library/react';
import { BushwalkingTypeEditor } from '../BushwalkingTypeEditor';

jest.mock('@/components/routes/RouteSelector', () => ({
  RouteSelector: () => <div data-testid='mock-route-selector' />,
}));

// Mock useRoute to avoid requiring a QueryClientProvider in unit tests
jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

describe('BushwalkingTypeEditor', () => {
  it('renders grading dropdown and route selector in create mode', () => {
    render(<BushwalkingTypeEditor createMode={true} />);

    expect(screen.getByText(/Australian Track Grading/i)).toBeInTheDocument();
    expect(screen.getByTestId('mock-route-selector')).toBeInTheDocument();
  });

  it('renders view mode with correct grading description', () => {
    render(
      <BushwalkingTypeEditor
        createMode={false}
        data={{ track_grading: 'Grade 3' }}
      />
    );

    expect(screen.getByText('Grade 3')).toBeInTheDocument();
    expect(
      screen.getByText(/Suitable for most ages and fitness levels/i)
    ).toBeInTheDocument();
  });
});
