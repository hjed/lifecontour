import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { TemplateSelector } from '../TemplateSelector';
import { ActivityTemplateType } from '@/types/journals';
import * as templatesApi from '@/lib/api/templates';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the API hooks
jest.mock('@/lib/api/templates', () => ({
  getTemplates: jest.fn(),
}));

const mockTemplates = [
  {
    type: 'activity-templates',
    id: '1',
    attributes: {
      name: 'Test Canyoning Template',
      template_type: ActivityTemplateType.CANYONING,
      pitches: [{ pitch_number: 1 }],
      french_grade: 'v3a2II',
    },
  },
  {
    type: 'activity-templates',
    id: '2',
    attributes: {
      name: 'Another Template',
      template_type: ActivityTemplateType.CANYONING,
      pitches: [],
    },
  },
];

describe('TemplateSelector', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    jest.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    (templatesApi.getTemplates as jest.Mock).mockResolvedValue({
      data: mockTemplates,
    });
  });

  const renderComponent = (props = {}) => {
    return render(
      <QueryClientProvider client={queryClient}>
        <TemplateSelector
          templateType={ActivityTemplateType.CANYONING}
          onSelect={jest.fn()}
          onCreateTemplate={jest.fn()}
          {...props}
        />
      </QueryClientProvider>
    );
  };

  it('renders correctly', () => {
    renderComponent();
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  it('disables the combobox when disabled prop is true', () => {
    renderComponent({ disabled: true });
    expect(screen.getByRole('combobox')).toBeDisabled();
  });

  it('displays templates and allows selection', async () => {
    const handleSelect = jest.fn();
    renderComponent({ onSelect: handleSelect });

    const combobox = screen.getByRole('combobox');
    act(() => {
      fireEvent.keyDown(combobox, { key: 'ArrowDown' });
    });

    await waitFor(() => {
      expect(screen.getByText('Test Canyoning Template')).toBeInTheDocument();
      expect(screen.getByText('Another Template')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Test Canyoning Template'));

    expect(handleSelect).toHaveBeenCalledWith(mockTemplates[0]);
    // It should close and clear the value
    expect(screen.getByRole('combobox')).toHaveValue('');
  });

  it('calls onCreateTemplate when create button is clicked', async () => {
    const handleCreate = jest.fn();
    renderComponent({ onCreateTemplate: handleCreate });

    const combobox = screen.getByRole('combobox');
    act(() => {
      fireEvent.keyDown(combobox, { key: 'ArrowDown' });
    });

    await waitFor(() => {
      const createButton = screen.getByText('+ Create new template');
      expect(createButton).toBeInTheDocument();
      fireEvent.click(createButton);
    });

    expect(handleCreate).toHaveBeenCalled();
  });
});
