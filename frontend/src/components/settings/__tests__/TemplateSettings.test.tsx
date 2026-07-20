import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TemplateSettings } from '../TemplateSettings';
import * as templatesApi from '@/lib/api/templates';

jest.mock('@/lib/api/templates', () => ({
  getTemplates: jest.fn(),
  deleteTemplate: jest.fn(),
  createTemplate: jest.fn(),
  updateTemplate: jest.fn(),
}));

const template = {
  type: 'activity-templates' as const,
  id: 'tpl-1',
  attributes: {
    name: 'Empress Canyon',
    template_type: 'canyoning',
    region: 'Blue Mountains',
    pitches: [{ pitch_number: 1, height: 30 }],
  },
};

describe('TemplateSettings', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    jest.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    (templatesApi.getTemplates as jest.Mock).mockResolvedValue({
      data: [template],
    });
  });

  const renderComponent = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <TemplateSettings />
      </QueryClientProvider>
    );

  it('renders an edit button for each template', async () => {
    renderComponent();

    expect(
      await screen.findByRole('button', {
        name: 'Edit template Empress Canyon',
      })
    ).toBeInTheDocument();
  });

  it('opens the edit dialog prefilled with the template', async () => {
    const user = userEvent.setup();
    renderComponent();

    await user.click(
      await screen.findByRole('button', {
        name: 'Edit template Empress Canyon',
      })
    );

    await waitFor(() => {
      expect(
        screen.getByRole('heading', { name: 'Edit Template' })
      ).toBeInTheDocument();
      expect(screen.getByLabelText('Template Name')).toHaveValue(
        'Empress Canyon'
      );
    });
  });
});
