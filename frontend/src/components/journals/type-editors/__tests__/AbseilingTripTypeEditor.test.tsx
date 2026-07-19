import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AbseilingTripTypeEditor } from '../AbseilingTripTypeEditor';
import {
  ActivityTemplateType,
  type ActivityTemplateResource,
} from '@/types/journals';

// The template selector is exercised through its own tests; mock it here so the
// abseiling editor tests do not depend on the templates query.
jest.mock('../TemplateSelector', () => ({
  TemplateSelector: ({
    onSelect,
    templateType,
  }: {
    onSelect: (template: ActivityTemplateResource) => void;
    templateType: ActivityTemplateType;
  }) => (
    <button
      data-testid='mock-template-selector'
      data-template-type={templateType}
      onClick={() =>
        onSelect({
          id: 'template-abseil-1',
          type: 'activity-templates',
          attributes: {
            name: 'Claustral Canyon',
            template_type: templateType,
            pitches: [
              { pitch_number: 1, height: 20 },
              { pitch_number: 2, height: 30 },
              { pitch_number: 3, height: 5, pitch_type: 'jump' },
            ],
          },
        })
      }
    >
      Select Template
    </button>
  ),
}));

jest.mock('../CreateTemplateDialog', () => ({
  CreateTemplateDialog: () => <div data-testid='mock-create-template-dialog' />,
}));

describe('AbseilingTripTypeEditor', () => {
  it('renders abseil count and total length inputs in create mode', () => {
    render(<AbseilingTripTypeEditor createMode={true} />);

    expect(screen.getByTestId('number-of-abseils-input')).toBeInTheDocument();
    expect(screen.getByTestId('total-length-input')).toBeInTheDocument();
  });

  it('shows an explicit zero abseil count in view mode for all-jump trips', () => {
    render(
      <AbseilingTripTypeEditor
        createMode={false}
        data={{
          number_of_abseils: 0,
          total_length: 8,
          pitches: [{ pitch_number: 1, height: 8, pitch_type: 'jump' }],
        }}
      />
    );

    const summary = screen.getByTestId('abseiling-trip-summary');
    expect(summary).toHaveTextContent('Abseils');
    expect(summary).toHaveTextContent('0');
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

  it('preserves both create-mode field updates when they are batched together', () => {
    const handleChange = jest.fn();

    render(
      <AbseilingTripTypeEditor createMode={true} onChange={handleChange} />
    );

    handleChange.mockClear();

    act(() => {
      fireEvent.change(screen.getByTestId('number-of-abseils-input'), {
        target: { value: '4' },
      });
      fireEvent.change(screen.getByTestId('total-length-input'), {
        target: { value: '120' },
      });
    });

    expect(handleChange).toHaveBeenLastCalledWith({
      number_of_abseils: 4,
      total_length: 120,
    });
  });

  it('renders an abseiling template selector in create mode', () => {
    render(<AbseilingTripTypeEditor createMode={true} />);

    const selector = screen.getByTestId('mock-template-selector');
    expect(selector).toBeInTheDocument();
    expect(selector).toHaveAttribute(
      'data-template-type',
      ActivityTemplateType.ABSEILING
    );
  });

  it('counts only abseil-type pitches when importing a template', async () => {
    const user = userEvent.setup();
    const handleChange = jest.fn();

    render(
      <AbseilingTripTypeEditor createMode={true} onChange={handleChange} />
    );

    await user.click(screen.getByTestId('mock-template-selector'));

    // The jump pitch descends 5m but is not an abseil.
    expect(handleChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        number_of_abseils: 2,
        total_length: 55,
      })
    );
  });

  it('keeps a zero abseil count when only jump pitches remain', async () => {
    const user = userEvent.setup();
    const handleChange = jest.fn();

    render(
      <AbseilingTripTypeEditor
        createMode={true}
        data={{
          pitches: [
            { pitch_number: 1, height: 20 },
            { pitch_number: 2, height: 5, pitch_type: 'jump' },
          ],
        }}
        onChange={handleChange}
      />
    );

    // Removing the only abseil leaves one jump pitch: zero abseils, not null.
    await user.click(screen.getByTestId('remove-pitch-0'));

    expect(handleChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ number_of_abseils: 0, total_length: 5 })
    );
  });

  it('treats a user-entered count over an all-jump pitch list as manual', async () => {
    const user = userEvent.setup();
    const handleChange = jest.fn();

    // Calculated abseils are 0 (both pitches are jumps) but the user has
    // entered 3 — that manual override must survive later pitch edits.
    render(
      <AbseilingTripTypeEditor
        createMode={true}
        data={{
          number_of_abseils: 3,
          pitches: [
            { pitch_number: 1, height: 5, pitch_type: 'jump' },
            { pitch_number: 2, height: 3, pitch_type: 'jump' },
          ],
        }}
        onChange={handleChange}
      />
    );

    await user.click(screen.getByTestId('remove-pitch-1'));

    expect(handleChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ number_of_abseils: 3 })
    );
  });

  it('calls onTemplateSelect with the selected template', async () => {
    const user = userEvent.setup();
    const onTemplateSelect = jest.fn();

    render(
      <AbseilingTripTypeEditor
        createMode={true}
        onTemplateSelect={onTemplateSelect}
      />
    );

    await user.click(screen.getByTestId('mock-template-selector'));

    expect(onTemplateSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'template-abseil-1',
        attributes: expect.objectContaining({ name: 'Claustral Canyon' }),
      })
    );
  });
});
