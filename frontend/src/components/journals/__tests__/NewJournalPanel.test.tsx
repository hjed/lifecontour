/**
 * @jest-environment jsdom
 */

import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { NewJournalPanel } from '../NewJournalPanel';
import { createMockAppRouter } from '@/test-utils/mock-router';

interface CapturedFormProps {
  readonly onSuccess?: (journalId: string) => void;
  readonly onCancel?: () => void;
  readonly onPendingChange?: (pending: boolean) => void;
}

// The form is exercised by its own tests; here it only reports what the
// panel handed it, so the panel's own decisions can be driven directly.
let formProps: CapturedFormProps = {};
jest.mock('@/components/journals/JournalCreateForm', () => ({
  JournalCreateForm: (props: CapturedFormProps) => {
    formProps = props;
    return (
      <button type='button' onClick={() => props.onCancel?.()}>
        Cancel
      </button>
    );
  },
}));

const calls: string[] = [];
const mockPush = jest.fn((href: string) => {
  calls.push(`push:${href}`);
});
const mockRouter = { ...createMockAppRouter(), push: mockPush };

jest.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
}));

describe('NewJournalPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    calls.length = 0;
    formProps = {};
  });

  it('reports the create, then opens the new journal', () => {
    const onCreated = jest.fn(() => {
      calls.push('created');
    });
    render(
      <NewJournalPanel
        onCreated={onCreated}
        onCancel={jest.fn()}
        onBusyChange={jest.fn()}
      />
    );

    act(() => formProps.onSuccess?.('j-1'));

    expect(calls).toEqual(['created', 'push:/journals/j-1']);
  });

  it('hands Cancel to the dialog without navigating', async () => {
    const user = userEvent.setup();
    const onCreated = jest.fn();
    const onCancel = jest.fn();
    render(
      <NewJournalPanel
        onCreated={onCreated}
        onCancel={onCancel}
        onBusyChange={jest.fn()}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onCreated).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('does nothing when the create settles after the panel has gone', () => {
    const onCreated = jest.fn();
    const { unmount } = render(
      <NewJournalPanel
        onCreated={onCreated}
        onCancel={jest.fn()}
        onBusyChange={jest.fn()}
      />
    );
    const settle = formProps.onSuccess;

    unmount();
    act(() => settle?.('j-late'));

    expect(onCreated).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("hands the form's pending state to the dialog", () => {
    const onBusyChange = jest.fn();
    render(
      <NewJournalPanel
        onCreated={jest.fn()}
        onCancel={jest.fn()}
        onBusyChange={onBusyChange}
      />
    );

    act(() => formProps.onPendingChange?.(true));
    expect(onBusyChange).toHaveBeenLastCalledWith(true);
    act(() => formProps.onPendingChange?.(false));
    expect(onBusyChange).toHaveBeenLastCalledWith(false);
  });
});
