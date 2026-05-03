import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ClimbingTypeEditor } from '../ClimbingTypeEditor';

jest.mock('@/lib/api/routes', () => ({
  useRoute: () => ({ data: undefined }),
}));

jest.mock('../TemplateSelector', () => ({
  TemplateSelector: ({ onSelect, templateType }: any) => {
    return (
      <button
        data-testid='mock-template-selector'
        onClick={() =>
          onSelect({
            id: 'template-123',
            attributes: {
              name: 'Test Template',
              template_type: templateType,
              climbing_type: 'sport',
              grade: 21,
              length: 30,
            },
          })
        }
      >
        Select Template
      </button>
    );
  },
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

describe('ClimbingTypeEditor', () => {
  it('updates form fields and calls onTemplateSelect when a template is selected in create mode', async () => {
    const user = userEvent.setup();
    const mockOnTemplateSelect = jest.fn();

    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <ClimbingTypeEditor
          createMode={true}
          onTemplateSelect={mockOnTemplateSelect}
        />
      </QueryClientProvider>
    );

    await user.click(screen.getByTestId('mock-template-selector'));

    await waitFor(() => {
      expect(screen.getByTestId('climbing-grade-input')).toHaveValue(21);
      expect(screen.getByTestId('climbing-length-input')).toHaveValue(30);
    });

    expect(mockOnTemplateSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'template-123',
        attributes: expect.objectContaining({
          climbing_type: 'sport',
          grade: 21,
        }),
      })
    );
  });
});
