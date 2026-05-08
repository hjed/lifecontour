import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OutdoorTrainingTypeEditor } from '../OutdoorTrainingTypeEditor';
import { useTypeEditorState } from '../useTypeEditorState';

// Mock the hook to isolate the component
jest.mock('../useTypeEditorState', () => ({
  useTypeEditorState: jest.fn(),
}));

// Mock GenericTypeEditorLayout to simplify testing
jest.mock('../GenericTypeEditorLayout', () => ({
  GenericTypeEditorLayout: ({
    children,
    summaryTestId,
    onEdit,
    onSave,
    onCancel,
    testId,
    summaryItems,
  }: any) => (
    <div data-testid={testId || 'generic-layout'}>
      <div data-testid={summaryTestId}>
        {summaryItems &&
          summaryItems.map((item: any, i: number) => (
            <div key={i}>
              {item.label}: {item.value}
            </div>
          ))}
      </div>
      <button onClick={onEdit} data-testid='edit-button'>
        Edit
      </button>
      <button onClick={onSave} data-testid='save-button'>
        Save
      </button>
      <button onClick={onCancel} data-testid='cancel-button'>
        Cancel
      </button>
      {children}
    </div>
  ),
  compactSummaryItems: jest
    .fn()
    .mockImplementation((...items) => items.flat().filter(Boolean)),
}));

const mockUseTypeEditorState = useTypeEditorState as jest.Mock;

describe('OutdoorTrainingTypeEditor', () => {
  const defaultHookState = {
    isEditing: false,
    editData: {},
    setEditData: jest.fn(),
    handleEdit: jest.fn(),
    handleSave: jest.fn(),
    handleCancel: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseTypeEditorState.mockReturnValue(defaultHookState);
  });

  it('renders read-only mode correctly', () => {
    render(
      <OutdoorTrainingTypeEditor
        data={{ focus_areas: ['abseiling_trip', 'bushwalking'] }}
      />
    );

    // The component formats the known activity names
    expect(
      screen.getByText(/Focus Areas: Abseiling, Bushwalking/)
    ).toBeInTheDocument();
  });

  it('allows adding a custom focus area when editing', async () => {
    const setEditDataMock = jest.fn();
    mockUseTypeEditorState.mockReturnValue({
      ...defaultHookState,
      isEditing: true,
      editData: { focus_areas: [] },
      setEditData: setEditDataMock,
    });

    render(<OutdoorTrainingTypeEditor />);

    const input = screen.getByTestId('custom-focus-area-input');
    await userEvent.type(input, 'Navigation');

    const addBtn = screen.getByTestId('add-focus-area-btn');
    await userEvent.click(addBtn);

    expect(setEditDataMock).toHaveBeenCalled();
    const updateFn = setEditDataMock.mock.calls[0][0];
    const newState = updateFn({ focus_areas: [] });
    expect(newState.focus_areas).toEqual(['Navigation']);
  });

  it('allows toggling known activity types when editing', async () => {
    const setEditDataMock = jest.fn();
    mockUseTypeEditorState.mockReturnValue({
      ...defaultHookState,
      isEditing: true,
      editData: { focus_areas: [] },
      setEditData: setEditDataMock,
    });

    render(<OutdoorTrainingTypeEditor />);

    const checkbox = screen.getByTestId('focus-area-checkbox-canyoning');
    await userEvent.click(checkbox);

    expect(setEditDataMock).toHaveBeenCalled();
    const updateFn = setEditDataMock.mock.calls[0][0];
    const newState = updateFn({ focus_areas: [] });
    expect(newState.focus_areas).toEqual(['canyoning']);
  });

  it('allows removing a focus area when editing', async () => {
    const setEditDataMock = jest.fn();
    mockUseTypeEditorState.mockReturnValue({
      ...defaultHookState,
      isEditing: true,
      editData: { focus_areas: ['canyoning'] },
      setEditData: setEditDataMock,
    });

    render(<OutdoorTrainingTypeEditor />);

    const removeBtn = screen.getByTestId('remove-focus-area-canyoning');
    await userEvent.click(removeBtn);

    expect(setEditDataMock).toHaveBeenCalled();
    const updateFn = setEditDataMock.mock.calls[0][0];
    const newState = updateFn({ focus_areas: ['canyoning'] });
    expect(newState.focus_areas).toBeNull(); // Empty array becomes null
  });
});
