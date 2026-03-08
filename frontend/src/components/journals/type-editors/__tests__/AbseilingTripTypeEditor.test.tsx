import { render, screen } from '@testing-library/react';
import { AbseilingTripTypeEditor } from '../AbseilingTripTypeEditor';

describe('AbseilingTripTypeEditor', () => {
  it('renders abseil count and total length inputs in create mode', () => {
    render(<AbseilingTripTypeEditor createMode={true} />);

    expect(screen.getByTestId('number-of-abseils-input')).toBeInTheDocument();
    expect(screen.getByTestId('total-length-input')).toBeInTheDocument();
  });

  it('renders view mode with abseiling summary values', () => {
    render(
      <AbseilingTripTypeEditor
        createMode={false}
        data={{ number_of_abseils: 4, total_length: 120 }}
      />
    );

    expect(screen.getByTestId('abseiling-trip-summary')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('120 m')).toBeInTheDocument();
  });
});
