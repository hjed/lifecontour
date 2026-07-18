import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { CreateTemplateDialog } from '../CreateTemplateDialog';
import { ActivityTemplateType } from '@/types/journals';
import * as templatesApi from '@/lib/api/templates';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

jest.mock('@/lib/api/templates', () => ({
  createTemplate: jest.fn(),
}));

describe('CreateTemplateDialog', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    jest.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  const renderComponent = (props = {}) => {
    return render(
      <QueryClientProvider client={queryClient}>
        <CreateTemplateDialog
          open={true}
          onOpenChange={jest.fn()}
          defaultTemplateType={ActivityTemplateType.CANYONING}
          onCreated={jest.fn()}
          {...props}
        />
      </QueryClientProvider>
    );
  };

  it('renders correctly', () => {
    renderComponent();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Create Template' })
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Template Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Region')).toBeInTheDocument();
    expect(screen.getByLabelText(/Description/i)).toBeInTheDocument();
    expect(screen.getByText('Standard Pitches')).toBeInTheDocument();
  });

  it('submits the form successfully and calls onCreated', async () => {
    const mockResponse = { data: { id: '1', attributes: { name: 'Test' } } };
    (templatesApi.createTemplate as jest.Mock).mockResolvedValue(mockResponse);

    const handleCreated = jest.fn();
    const handleOpenChange = jest.fn();

    renderComponent({
      onCreated: handleCreated,
      onOpenChange: handleOpenChange,
    });

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Template Name'), {
        target: { value: 'Test Template' },
      });
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Create Template' }));
    });

    await waitFor(() => {
      expect(templatesApi.createTemplate).toHaveBeenCalledWith({
        data: {
          type: 'activity-templates',
          attributes: {
            name: 'Test Template',
            template_type: ActivityTemplateType.CANYONING,
            description: null,
            region: null,
            pitches: null,
          },
        },
      });
      expect(handleCreated).toHaveBeenCalledWith(mockResponse.data);
      expect(handleOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it('includes pitch notes in the create payload', async () => {
    const mockResponse = { data: { id: '1', attributes: { name: 'Test' } } };
    (templatesApi.createTemplate as jest.Mock).mockResolvedValue(mockResponse);

    renderComponent({
      initialPitches: [
        {
          pitch_number: 1,
          height: 30,
          anchor_location: null,
          anchor_type: null,
          did_rescue: null,
          did_setup: null,
          notes: 'Awkward start over the chockstone',
        },
      ],
    });

    await act(async () => {
      fireEvent.change(screen.getByLabelText('Template Name'), {
        target: { value: 'Notes Template' },
      });
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Create Template' }));
    });

    await waitFor(() => {
      expect(templatesApi.createTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            attributes: expect.objectContaining({
              pitches: [
                expect.objectContaining({
                  pitch_number: 1,
                  notes: 'Awkward start over the chockstone',
                }),
              ],
            }),
          }),
        })
      );
    });
  });

  it('shows validation error if name is empty', async () => {
    renderComponent();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Create Template' }));
    });

    await waitFor(() => {
      expect(screen.getByText('Name is required')).toBeInTheDocument();
    });
  });
});
