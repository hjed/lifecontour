import { render, screen } from '@testing-library/react';
import { ClimbingTypeEditor } from '../ClimbingTypeEditor';
import { CrossCountrySkiingTypeEditor } from '../CrossCountrySkiingTypeEditor';
import { KayakingTypeEditor } from '../KayakingTypeEditor';

jest.mock('@/components/routes/RouteSelector', () => ({
  RouteSelector: () => <div data-testid='mock-route-selector' />,
}));

jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

const routeBackedEditorCases = [
  {
    name: 'ClimbingTypeEditor',
    renderCreate: () => render(<ClimbingTypeEditor createMode={true} />),
    assertCreate: () => {
      expect(screen.getByText(/Climbing Type/i)).toBeInTheDocument();
      expect(screen.getByTestId('climbing-grade-input')).toBeInTheDocument();
      expect(screen.getByTestId('climbing-length-input')).toBeInTheDocument();
    },
    renderView: () =>
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
      ),
    summaryTestId: 'climbing-summary',
    summaryTexts: ['sport', '18', '30 m', 'route-123'],
  },
  {
    name: 'KayakingTypeEditor',
    renderCreate: () => render(<KayakingTypeEditor createMode={true} />),
    assertCreate: () => {
      expect(screen.getByTestId('water-type-input')).toBeInTheDocument();
    },
    renderView: () =>
      render(
        <KayakingTypeEditor
          createMode={false}
          data={{ route_id: 'route-123', water_type: 'river' }}
        />
      ),
    summaryTestId: 'kayaking-summary',
    summaryTexts: ['river', 'route-123'],
  },
  {
    name: 'CrossCountrySkiingTypeEditor',
    renderCreate: () =>
      render(<CrossCountrySkiingTypeEditor createMode={true} />),
    assertCreate: () => {
      expect(screen.getByTestId('snow-conditions-input')).toBeInTheDocument();
    },
    renderView: () =>
      render(
        <CrossCountrySkiingTypeEditor
          createMode={false}
          data={{ route_id: 'route-123', snow_conditions: 'Fresh powder' }}
        />
      ),
    summaryTestId: 'cross-country-skiing-summary',
    summaryTexts: ['Fresh powder', 'route-123'],
  },
] as const;

describe.each(routeBackedEditorCases)('$name', testCase => {
  it('renders route-backed controls in create mode', () => {
    testCase.renderCreate();

    expect(screen.getByTestId('mock-route-selector')).toBeInTheDocument();
    testCase.assertCreate();
  });

  it('renders route-backed summary values in view mode', () => {
    testCase.renderView();

    expect(screen.getByTestId(testCase.summaryTestId)).toBeInTheDocument();
    for (const text of testCase.summaryTexts) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });
});
