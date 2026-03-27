/**
 * @jest-environment jsdom
 */

/**
 * Tests for JournalSearchCombobox component.
 *
 * Focuses on the onClear callback behaviour when the user clears the input.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JournalSearchCombobox } from '../JournalSearchCombobox';

// Mock fetch so useQuery doesn't make real requests
const mockFetch = jest.fn(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ data: [], meta: {} }),
  })
);

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = 'TestWrapper';
  return Wrapper;
};

describe('JournalSearchCombobox', () => {
  beforeEach(() => {
    mockFetch.mockClear();
    globalThis.fetch = mockFetch as unknown as typeof fetch;
  });

  it('renders with placeholder text', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <JournalSearchCombobox
          onSelect={jest.fn()}
          placeholder='Search journals...'
        />
      </Wrapper>
    );

    expect(
      screen.getByPlaceholderText('Search journals...')
    ).toBeInTheDocument();
  });

  it('calls onClear when the input is fully cleared', async () => {
    const user = userEvent.setup();
    const onClear = jest.fn();
    const Wrapper = createWrapper();

    render(
      <Wrapper>
        <JournalSearchCombobox
          onSelect={jest.fn()}
          onClear={onClear}
          value='Existing Parent'
          placeholder='Search journals...'
        />
      </Wrapper>
    );

    const input = screen.getByPlaceholderText(
      'Search journals...'
    ) as HTMLInputElement;

    // The input should start with the pre-populated value
    expect(input.value).toBe('Existing Parent');

    // Clear the input — this triggers handleInputChange with empty string
    await user.clear(input);
    expect(input.value).toBe('');
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('does not call onClear when onClear is not provided', async () => {
    const user = userEvent.setup();
    const Wrapper = createWrapper();

    render(
      <Wrapper>
        <JournalSearchCombobox
          onSelect={jest.fn()}
          placeholder='Search journals...'
        />
      </Wrapper>
    );

    const input = screen.getByPlaceholderText(
      'Search journals...'
    ) as HTMLInputElement;

    // Type and clear — should not throw
    await user.type(input, 'something');
    await user.clear(input);
    expect(input.value).toBe('');
  });

  it('does not call onClear while text remains in the input', async () => {
    const user = userEvent.setup();
    const onClear = jest.fn();
    const Wrapper = createWrapper();

    render(
      <Wrapper>
        <JournalSearchCombobox
          onSelect={jest.fn()}
          onClear={onClear}
          placeholder='Search journals...'
        />
      </Wrapper>
    );

    const input = screen.getByPlaceholderText(
      'Search journals...'
    ) as HTMLInputElement;

    // Type some text — onClear should NOT fire
    await user.type(input, 'Parent');
    expect(onClear).not.toHaveBeenCalled();
    expect(input.value).toBe('Parent');
  });

  it('calls onClear when user deletes all text via backspace', async () => {
    const user = userEvent.setup();
    const onClear = jest.fn();
    const Wrapper = createWrapper();

    render(
      <Wrapper>
        <JournalSearchCombobox
          onSelect={jest.fn()}
          onClear={onClear}
          placeholder='Search journals...'
        />
      </Wrapper>
    );

    const input = screen.getByPlaceholderText(
      'Search journals...'
    ) as HTMLInputElement;

    // Type a single character then delete it
    await user.type(input, 'a');
    expect(onClear).not.toHaveBeenCalled();

    await user.type(input, '{Backspace}');
    expect(input.value).toBe('');
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('initialises with value prop and syncs on change', () => {
    const Wrapper = createWrapper();
    const { rerender } = render(
      <Wrapper>
        <JournalSearchCombobox
          onSelect={jest.fn()}
          value='Original Title'
          placeholder='Search journals...'
        />
      </Wrapper>
    );

    const input = screen.getByPlaceholderText(
      'Search journals...'
    ) as HTMLInputElement;
    expect(input.value).toBe('Original Title');

    // Re-render with new value
    rerender(
      <Wrapper>
        <JournalSearchCombobox
          onSelect={jest.fn()}
          value='Updated Title'
          placeholder='Search journals...'
        />
      </Wrapper>
    );

    expect(input.value).toBe('Updated Title');
  });
});
