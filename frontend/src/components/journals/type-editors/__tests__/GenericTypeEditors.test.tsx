import { render, screen } from '@testing-library/react';
import { BushwalkingTypeEditor } from '../BushwalkingTypeEditor';
import { ClimbingTypeEditor } from '../ClimbingTypeEditor';
import { CrossCountrySkiingTypeEditor } from '../CrossCountrySkiingTypeEditor';
import { JoggingTypeEditor } from '../JoggingTypeEditor';
import { KayakingTypeEditor } from '../KayakingTypeEditor';

jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

const genericEditorCases = [
  {
    name: 'BushwalkingTypeEditor',
    renderCreate: () => render(<BushwalkingTypeEditor createMode={true} />),
    assertCreate: () => {
      expect(screen.getByText(/Australian Track Grading/i)).toBeInTheDocument();
    },
    renderView: () =>
      render(
        <BushwalkingTypeEditor
          createMode={false}
          data={{ track_grading: 'Grade 4' }}
        />
      ),
    summaryTexts: ['Grade 4'],
    summaryTestId: 'bushwalking-type-editor',
    renderEmptyView: () =>
      render(<BushwalkingTypeEditor createMode={false} data={{}} />),
    emptyMessage: 'No bushwalking details provided.',
  },
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
            climbing_type: 'sport',
            grade: 18,
            length: 30,
          }}
        />
      ),
    summaryTestId: 'climbing-summary',
    summaryTexts: ['sport', '18', '30 m'],
    renderEmptyView: () =>
      render(<ClimbingTypeEditor createMode={false} data={{}} />),
    emptyMessage: 'No climbing details provided.',
  },
  {
    name: 'KayakingTypeEditor',
    renderCreate: () => render(<KayakingTypeEditor createMode={true} />),
    assertCreate: () => {
      expect(screen.getByTestId('water-type-input')).toBeInTheDocument();
    },
    renderView: () =>
      render(
        <KayakingTypeEditor createMode={false} data={{ water_type: 'river' }} />
      ),
    summaryTestId: 'kayaking-summary',
    summaryTexts: ['river'],
    renderEmptyView: () =>
      render(<KayakingTypeEditor createMode={false} data={{}} />),
    emptyMessage: 'No kayaking details provided.',
  },
  {
    name: 'JoggingTypeEditor',
    renderCreate: () => render(<JoggingTypeEditor createMode={true} />),
    assertCreate: () => {
      expect(screen.getByTestId('pace-input')).toBeInTheDocument();
    },
    renderView: () =>
      render(<JoggingTypeEditor createMode={false} data={{ pace: 330 }} />),
    summaryTexts: ['5:30 /km'],
    summaryTestId: 'jogging-type-editor',
    renderEmptyView: () =>
      render(<JoggingTypeEditor createMode={false} data={{}} />),
    emptyMessage: 'No jogging details provided.',
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
          data={{ snow_conditions: 'Fresh powder' }}
        />
      ),
    summaryTestId: 'cross-country-skiing-summary',
    summaryTexts: ['Fresh powder'],
    renderEmptyView: () =>
      render(<CrossCountrySkiingTypeEditor createMode={false} data={{}} />),
    emptyMessage: 'No cross-country skiing details provided.',
  },
] as const;

describe.each(genericEditorCases)('$name', testCase => {
  it('renders correctly in create mode', () => {
    testCase.renderCreate();
    testCase.assertCreate();
  });

  it('renders route-backed summary values in view mode', () => {
    testCase.renderView();

    expect(screen.getByTestId(testCase.summaryTestId)).toBeInTheDocument();
    for (const text of testCase.summaryTexts) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it('renders the empty read-only state when no type data exists', () => {
    testCase.renderEmptyView();

    expect(screen.getByText(testCase.emptyMessage)).toBeInTheDocument();
    expect(screen.getByTestId('edit-button')).toBeInTheDocument();
  });
});
