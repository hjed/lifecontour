/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ImportantDateInlineEditor } from '../ImportantDateInlineEditor';
import {
  ImportantDatePrecision,
  ImportantDateTypeEnum,
} from '@/types/contacts';
import * as contactsApi from '@/lib/api/contacts';

jest.mock('@/lib/api/contacts', () => ({
  useCustomDateTypes: jest.fn(),
  useCreateCustomDateType: jest.fn(),
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const TestWrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  TestWrapper.displayName = 'TestWrapper';
  return TestWrapper;
};

describe('ImportantDateInlineEditor', () => {
  const mockOnSave = jest.fn();
  const mockOnCancel = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    (contactsApi.useCustomDateTypes as jest.Mock).mockReturnValue({
      data: { data: [] },
    });
    (contactsApi.useCreateCustomDateType as jest.Mock).mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    });

    mockOnSave.mockResolvedValue(undefined);
  });

  const renderEditor = () =>
    render(
      <ImportantDateInlineEditor onSave={mockOnSave} onCancel={mockOnCancel} />,
      { wrapper: createWrapper() }
    );

  it('renders the editor with default fields', () => {
    renderEditor();
    expect(
      screen.getByRole('combobox', { name: 'Important Date Type' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('combobox', { name: 'Important Date Precision' })
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Save date')).toBeInTheDocument();
    expect(screen.getByLabelText('Cancel edit')).toBeInTheDocument();
  });

  it('calls onSave with correct full-date payload', async () => {
    const user = userEvent.setup();
    renderEditor();

    // Fill in day, month, year (default precision is FULL)
    await user.clear(screen.getByPlaceholderText('DD'));
    await user.type(screen.getByPlaceholderText('DD'), '25');
    await user.clear(screen.getByPlaceholderText('MM'));
    await user.type(screen.getByPlaceholderText('MM'), '10');
    await user.clear(screen.getByPlaceholderText('YYYY'));
    await user.type(screen.getByPlaceholderText('YYYY'), '1990');

    await user.click(screen.getByLabelText('Save date'));

    await waitFor(() => {
      expect(mockOnSave).toHaveBeenCalledWith(
        expect.objectContaining({
          date_type: ImportantDateTypeEnum.BIRTHDAY,
          precision: ImportantDatePrecision.FULL,
          year: 1990,
          month: 10,
          day: 25,
        })
      );
    });
  });

  it('builds year-only payload with null month and day when precision is YEAR', async () => {
    const user = userEvent.setup();
    renderEditor();

    // Change precision to YEAR
    await user.click(
      screen.getByRole('combobox', { name: 'Important Date Precision' })
    );
    await user.click(screen.getByRole('option', { name: 'Year Only' }));

    await user.type(screen.getByPlaceholderText('YYYY'), '2005');
    await user.click(screen.getByLabelText('Save date'));

    await waitFor(() => {
      expect(mockOnSave).toHaveBeenCalledWith(
        expect.objectContaining({
          precision: ImportantDatePrecision.YEAR,
          year: 2005,
          month: null,
          day: null,
        })
      );
    });
  });

  it('does not call onSave when required fields are missing', async () => {
    const user = userEvent.setup();
    renderEditor();

    // Don't fill any fields — FULL precision requires year, month, day
    await user.click(screen.getByLabelText('Save date'));

    await waitFor(() => {
      expect(mockOnSave).not.toHaveBeenCalled();
    });
  });

  it('disables save button while onSave promise is in flight', async () => {
    // Make onSave take a tick to resolve so we can check disabled state
    let resolveSave!: () => void;
    mockOnSave.mockImplementation(
      () => new Promise<void>(res => (resolveSave = res))
    );

    const user = userEvent.setup();
    renderEditor();

    await user.type(screen.getByPlaceholderText('DD'), '1');
    await user.type(screen.getByPlaceholderText('MM'), '1');
    await user.type(screen.getByPlaceholderText('YYYY'), '2000');

    await user.click(screen.getByLabelText('Save date'));

    // While saving the button should be disabled
    await waitFor(() => {
      expect(screen.getByLabelText('Save date')).toBeDisabled();
    });

    resolveSave();

    await waitFor(() => {
      expect(mockOnSave).toHaveBeenCalledTimes(1);
    });
  });

  it('disables buttons when createCustomMutation is pending', () => {
    (contactsApi.useCreateCustomDateType as jest.Mock).mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: true,
    });

    renderEditor();

    expect(screen.getByLabelText('Save date')).toBeDisabled();
    expect(screen.getByLabelText('Cancel edit')).toBeDisabled();
  });

  it('calls onCancel when cancel button is clicked', async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByLabelText('Cancel edit'));
    expect(mockOnCancel).toHaveBeenCalled();
  });

  it('disables all inputs when isLoading prop is true', () => {
    render(
      <ImportantDateInlineEditor
        onSave={mockOnSave}
        onCancel={mockOnCancel}
        isLoading
      />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByLabelText('Save date')).toBeDisabled();
    expect(screen.getByLabelText('Cancel edit')).toBeDisabled();
  });
});
