/**
 * @jest-environment jsdom
 */

/**
 * Tests for JournalSearchCombobox component.
 *
 * Focuses on the onClear callback behaviour when the user clears the input.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JournalSearchCombobox } from '../JournalSearchCombobox';

// `jest.setup.ts` trims `@/lib/constants` to the auth endpoints, and the
// search reads the journals endpoint from it.
jest.mock('@/lib/constants', () => jest.requireActual('@/lib/constants'));

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

describe('JournalSearchCombobox inside a form field', () => {
  const RESULTS = {
    data: [
      {
        id: '5',
        type: 'journals',
        attributes: {
          title: 'Trip planning',
          event_date_range: {
            start: '2026-08-01T10:00:00Z',
            end: '2026-08-01T11:00:00Z',
          },
        },
      },
    ],
    meta: { total: 1 },
  };

  beforeEach(() => {
    globalThis.fetch = jest.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(RESULTS) })
    ) as unknown as typeof fetch;
  });

  it('carries the invalid state and the description a form field gives it', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <JournalSearchCombobox
          onSelect={jest.fn()}
          inputId='creating'
          invalid
          describedById='creating-description creating-message'
        />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAttribute(
      'aria-describedby',
      'creating-description creating-message'
    );
  });

  it('says nothing about validity when no field asks it to', () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <JournalSearchCombobox onSelect={jest.fn()} />
      </Wrapper>
    );

    const input = screen.getByRole('combobox');
    expect(input).not.toHaveAttribute('aria-invalid');
    expect(input).not.toHaveAttribute('aria-describedby');
  });

  /**
   * The New dialog mounts the journal form's parent search and the task
   * form's creating-journal search at once, so a fixed listbox id would be
   * shared by two elements and `aria-controls` would point at either.
   */
  it('gives each mounted search its own listbox', async () => {
    const Wrapper = createWrapper();
    render(
      <Wrapper>
        <JournalSearchCombobox onSelect={jest.fn()} placeholder='First' />
        <JournalSearchCombobox onSelect={jest.fn()} placeholder='Second' />
      </Wrapper>
    );

    const first = screen.getByPlaceholderText('First');
    const second = screen.getByPlaceholderText('Second');
    // `change` rather than typing: focusing the second would blur the first
    // and close its results, and both lists are wanted open at once.
    fireEvent.change(first, { target: { value: 'Trip' } });
    fireEvent.change(second, { target: { value: 'Trip' } });

    // Each search debounces on its own timer, so wait for both lists rather
    // than the first one to render.
    await waitFor(() => expect(screen.getAllByRole('listbox')).toHaveLength(2));
    const listboxes = screen.getAllByRole('listbox');
    const [firstList, secondList] = listboxes;
    expect(firstList.id).not.toBe(secondList.id);
    expect(first).toHaveAttribute('aria-controls', firstList.id);
    expect(second).toHaveAttribute('aria-controls', secondList.id);
  });
});
