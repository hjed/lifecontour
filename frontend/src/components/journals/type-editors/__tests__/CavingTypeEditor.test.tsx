import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CavingTypeEditor } from '../CavingTypeEditor';
import {
  ActivityTemplateType,
  type ActivityTemplateResource,
} from '@/types/journals';

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
      onClick={() =>
        onSelect({
          id: 'template-cave-1',
          type: 'activity-templates',
          attributes: {
            name: 'Jenolan Cave',
            template_type: templateType,
            is_vertical: true,
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

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

describe('CavingTypeEditor', () => {
  it('renders vertical and horizontal switches in create mode', () => {
    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <CavingTypeEditor createMode={true} />
      </QueryClientProvider>
    );

    expect(screen.getByTestId('vertical-switch')).toBeInTheDocument();
    expect(screen.getByTestId('horizontal-switch')).toBeInTheDocument();
  });

  it('populates fields and calls onTemplateSelect but does not write template_id onto the caving block', async () => {
    const user = userEvent.setup();
    const handleChange = jest.fn();
    const onTemplateSelect = jest.fn();

    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <CavingTypeEditor
          createMode={true}
          onChange={handleChange}
          onTemplateSelect={onTemplateSelect}
        />
      </QueryClientProvider>
    );

    await user.click(screen.getByTestId('mock-template-selector'));

    await waitFor(() => {
      expect(handleChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ is_vertical: true })
      );
    });

    expect(onTemplateSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'template-cave-1' })
    );
    // template_id now lives only on the consolidated abseiling block.
    expect(handleChange).not.toHaveBeenCalledWith(
      expect.objectContaining({ template_id: expect.anything() })
    );
  });
});
