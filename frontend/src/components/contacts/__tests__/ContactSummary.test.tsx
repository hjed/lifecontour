/**
 * Unit tests for ContactSummary component.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContactSummary } from '@/components/contacts/ContactSummary';
import {
  ContactSummaryDisabledReason,
  ContactSummaryResource,
  ContactSummaryStatus,
} from '@/types/contacts';

const mockMutate = jest.fn();
const mockRefreshHook = jest.fn();
const mockUpdateMutate = jest.fn();
const mockUpdateHook = jest.fn();

jest.mock('@/lib/api/contacts', () => ({
  useRefreshContactSummary: (...args: unknown[]) => mockRefreshHook(...args),
  useUpdateContactSummary: (...args: unknown[]) => mockUpdateHook(...args),
}));

function makeSummary(
  overrides: Partial<ContactSummaryResource['attributes']> = {}
): ContactSummaryResource {
  return {
    type: 'contact_summaries',
    id: '1',
    attributes: {
      summary_text: 'Test summary text',
      follow_up_suggestions: [],
      status: ContactSummaryStatus.GENERATED,
      is_disabled: false,
      disabled_reason: null,
      is_user_override: false,
      user_override_text: null,
      generated_at: '2026-01-01T00:00:00Z',
      ...overrides,
    },
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockRefreshHook.mockReturnValue({
    mutate: mockMutate,
    isPending: false,
  });
  mockUpdateHook.mockReturnValue({
    mutate: mockUpdateMutate,
    isPending: false,
  });
});

const userDisabled = {
  status: ContactSummaryStatus.DISABLED,
  is_disabled: true,
  disabled_reason: ContactSummaryDisabledReason.USER,
};

const autoPaused = {
  status: ContactSummaryStatus.DISABLED,
  is_disabled: true,
  disabled_reason: ContactSummaryDisabledReason.LOW_ACTIVITY,
};

function generationSwitch() {
  return screen.getByRole('switch', { name: /ai generation/i });
}

describe('ContactSummary', () => {
  describe('empty state', () => {
    it('renders empty state when summary is null', () => {
      render(<ContactSummary summary={null} contactId='1' />);

      expect(screen.getByTestId('contact-summary')).toBeInTheDocument();
      expect(screen.getByTestId('summary-empty-state')).toBeInTheDocument();
      expect(screen.getByText(/no ai summary available/i)).toBeInTheDocument();
    });

    it('renders empty state when summary is undefined', () => {
      render(<ContactSummary summary={undefined} contactId='1' />);

      expect(screen.getByTestId('summary-empty-state')).toBeInTheDocument();
    });
  });

  describe('status badge', () => {
    it('shows Generated badge for generated status', () => {
      render(<ContactSummary summary={makeSummary()} contactId='1' />);

      const badge = screen.getByTestId('summary-status-badge');
      expect(badge).toHaveTextContent('Generated');
    });

    it('shows Pending badge for pending status', () => {
      render(
        <ContactSummary
          summary={makeSummary({ status: ContactSummaryStatus.PENDING })}
          contactId='1'
        />
      );

      expect(screen.getByTestId('summary-status-badge')).toHaveTextContent(
        'Pending'
      );
    });

    it('shows Generating badge for generating status', () => {
      render(
        <ContactSummary
          summary={makeSummary({ status: ContactSummaryStatus.GENERATING })}
          contactId='1'
        />
      );

      expect(screen.getByTestId('summary-status-badge')).toHaveTextContent(
        'Generating'
      );
    });

    it('shows Failed badge for failed status', () => {
      render(
        <ContactSummary
          summary={makeSummary({ status: ContactSummaryStatus.FAILED })}
          contactId='1'
        />
      );

      expect(screen.getByTestId('summary-status-badge')).toHaveTextContent(
        'Failed'
      );
    });

    it('shows Disabled badge for disabled status', () => {
      render(
        <ContactSummary summary={makeSummary(userDisabled)} contactId='1' />
      );

      expect(screen.getByTestId('summary-status-badge')).toHaveTextContent(
        'Disabled'
      );
    });
  });

  describe('summary text', () => {
    it('displays summary text when generated', () => {
      render(
        <ContactSummary
          summary={makeSummary({ summary_text: 'This is a great contact.' })}
          contactId='1'
        />
      );

      expect(screen.getByTestId('summary-text')).toBeInTheDocument();
      expect(screen.getByText('This is a great contact.')).toBeInTheDocument();
    });

    it('displays user override text when is_user_override is true', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            summary_text: 'AI generated text',
            is_user_override: true,
            user_override_text: 'User custom text',
          })}
          contactId='1'
        />
      );

      expect(screen.getByText('User custom text')).toBeInTheDocument();
      expect(screen.queryByText('AI generated text')).not.toBeInTheDocument();
      expect(screen.getByTestId('summary-override-badge')).toHaveTextContent(
        'User Override'
      );
    });

    it('shows disabled message when status is disabled', () => {
      render(
        <ContactSummary
          summary={makeSummary({ ...userDisabled, summary_text: null })}
          contactId='1'
        />
      );

      expect(
        screen.getByText(/ai summary generation is disabled/i)
      ).toBeInTheDocument();
    });

    it('shows pending message when status is pending', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            status: ContactSummaryStatus.PENDING,
            summary_text: null,
          })}
          contactId='1'
        />
      );

      expect(
        screen.getByText(/summary generation is pending/i)
      ).toBeInTheDocument();
    });

    it('shows generating message when status is generating', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            status: ContactSummaryStatus.GENERATING,
            summary_text: null,
          })}
          contactId='1'
        />
      );

      expect(
        screen.getByText(/summary is being generated/i)
      ).toBeInTheDocument();
    });

    it('shows failed message when status is failed', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            status: ContactSummaryStatus.FAILED,
            summary_text: null,
          })}
          contactId='1'
        />
      );

      expect(
        screen.getByText(/ai summary generation failed/i)
      ).toBeInTheDocument();
    });

    it('hides stale AI text when status is not GENERATED', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            status: ContactSummaryStatus.GENERATING,
            summary_text: 'Stale text from previous generation',
          })}
          contactId='1'
        />
      );

      expect(
        screen.queryByText('Stale text from previous generation')
      ).not.toBeInTheDocument();
      expect(
        screen.getByText(/summary is being generated/i)
      ).toBeInTheDocument();
    });
  });

  describe('follow-up suggestions', () => {
    it('displays follow-up suggestions when available', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            follow_up_suggestions: ['Call them', 'Send birthday card'],
          })}
          contactId='1'
        />
      );

      expect(screen.getByTestId('summary-suggestions')).toBeInTheDocument();
      expect(screen.getByText('Call them')).toBeInTheDocument();
      expect(screen.getByText('Send birthday card')).toBeInTheDocument();
      expect(screen.getByText('Suggested Actions')).toBeInTheDocument();
    });

    it('hides suggestions section when list is empty', () => {
      render(
        <ContactSummary
          summary={makeSummary({ follow_up_suggestions: [] })}
          contactId='1'
        />
      );

      expect(
        screen.queryByTestId('summary-suggestions')
      ).not.toBeInTheDocument();
    });
  });

  describe('refresh button', () => {
    it('renders refresh button', () => {
      render(<ContactSummary summary={makeSummary()} contactId='1' />);

      expect(screen.getByTestId('summary-refresh-button')).toBeInTheDocument();
    });

    it('disables refresh button when the user disabled the summary', () => {
      render(
        <ContactSummary summary={makeSummary(userDisabled)} contactId='1' />
      );

      expect(screen.getByTestId('summary-refresh-button')).toBeDisabled();
    });

    it('disables refresh button when component is disabled', () => {
      render(
        <ContactSummary summary={makeSummary()} contactId='1' disabled={true} />
      );

      expect(screen.getByTestId('summary-refresh-button')).toBeDisabled();
    });

    it('calls refresh mutation when clicked', async () => {
      const user = userEvent.setup();
      render(<ContactSummary summary={makeSummary()} contactId='42' />);

      await user.click(screen.getByTestId('summary-refresh-button'));

      expect(mockMutate).toHaveBeenCalledTimes(1);
    });

    it('shows spinning icon when refresh is pending', () => {
      mockRefreshHook.mockReturnValue({
        mutate: mockMutate,
        isPending: true,
      });
      render(<ContactSummary summary={makeSummary()} contactId='1' />);

      const refreshButton = screen.getByTestId('summary-refresh-button');
      const icon = refreshButton.querySelector('svg');
      expect(icon).toHaveClass('animate-spin');
    });
  });

  describe('generated_at timestamp', () => {
    it('displays relative timestamp when status is GENERATED and generated_at is set', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            status: ContactSummaryStatus.GENERATED,
            generated_at: '2026-01-01T00:00:00Z',
          })}
          contactId='1'
        />
      );

      expect(screen.getByTestId('summary-generated-at')).toBeInTheDocument();
      // Should contain "Last generated" text
      expect(screen.getByTestId('summary-generated-at')).toHaveTextContent(
        /last generated/i
      );
    });

    it('does not show timestamp when generated_at is null', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            status: ContactSummaryStatus.GENERATED,
            generated_at: null,
          })}
          contactId='1'
        />
      );

      expect(
        screen.queryByTestId('summary-generated-at')
      ).not.toBeInTheDocument();
    });

    it('does not show timestamp when status is not GENERATED', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            status: ContactSummaryStatus.PENDING,
            generated_at: '2026-01-01T00:00:00Z',
          })}
          contactId='1'
        />
      );

      expect(
        screen.queryByTestId('summary-generated-at')
      ).not.toBeInTheDocument();
    });
  });

  describe('accessibility', () => {
    it('has proper aria-label on refresh button', () => {
      render(<ContactSummary summary={makeSummary()} contactId='1' />);

      expect(
        screen.getByRole('button', { name: /refresh ai summary/i })
      ).toBeInTheDocument();
    });
  });
  describe('generation switch', () => {
    it('passes the contact id to the update hook', () => {
      render(<ContactSummary summary={makeSummary()} contactId='42' />);

      expect(mockUpdateHook).toHaveBeenCalledWith('42');
    });

    it('is on when generation is enabled', () => {
      render(<ContactSummary summary={makeSummary()} contactId='1' />);

      expect(generationSwitch()).toBeChecked();
    });

    it('stays on while generation is paused for low activity', () => {
      render(
        <ContactSummary summary={makeSummary(autoPaused)} contactId='1' />
      );

      expect(generationSwitch()).toBeChecked();
    });

    it('is off when the user disabled generation', () => {
      render(
        <ContactSummary summary={makeSummary(userDisabled)} contactId='1' />
      );

      expect(generationSwitch()).not.toBeChecked();
    });

    it('turns generation off when switched off', async () => {
      const user = userEvent.setup();
      render(<ContactSummary summary={makeSummary()} contactId='1' />);

      await user.click(generationSwitch());

      expect(mockUpdateMutate).toHaveBeenCalledWith({ is_disabled: true });
    });

    it('turns a paused summary off as the user choice when switched off', async () => {
      const user = userEvent.setup();
      render(
        <ContactSummary summary={makeSummary(autoPaused)} contactId='1' />
      );

      await user.click(generationSwitch());

      expect(mockUpdateMutate).toHaveBeenCalledWith({ is_disabled: true });
    });

    it('turns generation back on when switched on', async () => {
      const user = userEvent.setup();
      render(
        <ContactSummary summary={makeSummary(userDisabled)} contactId='1' />
      );

      await user.click(generationSwitch());

      expect(mockUpdateMutate).toHaveBeenCalledWith({ is_disabled: false });
    });

    it('is disabled while an update is in flight', () => {
      mockUpdateHook.mockReturnValue({
        mutate: mockUpdateMutate,
        isPending: true,
      });
      render(<ContactSummary summary={makeSummary()} contactId='1' />);

      expect(generationSwitch()).toBeDisabled();
    });

    it('is disabled when the component is disabled', () => {
      render(
        <ContactSummary summary={makeSummary()} contactId='1' disabled={true} />
      );

      expect(generationSwitch()).toBeDisabled();
    });

    it('is shown on in the empty state and can turn generation off', async () => {
      const user = userEvent.setup();
      render(<ContactSummary summary={null} contactId='1' />);

      expect(generationSwitch()).toBeChecked();
      await user.click(generationSwitch());

      expect(mockUpdateMutate).toHaveBeenCalledWith({ is_disabled: true });
    });
  });

  describe('paused for low activity', () => {
    it('shows a Paused badge', () => {
      render(
        <ContactSummary summary={makeSummary(autoPaused)} contactId='1' />
      );

      expect(screen.getByTestId('summary-status-badge')).toHaveTextContent(
        'Paused'
      );
    });

    it('explains the pause resumes automatically', () => {
      render(
        <ContactSummary
          summary={makeSummary({ ...autoPaused, summary_text: null })}
          contactId='1'
        />
      );

      expect(
        screen.getByText(/paused.*not enough recent activity/i)
      ).toBeInTheDocument();
      expect(screen.getByText(/resumes automatically/i)).toBeInTheDocument();
    });

    it('keeps the refresh button enabled so activity can be re-checked', () => {
      render(
        <ContactSummary summary={makeSummary(autoPaused)} contactId='1' />
      );

      expect(screen.getByTestId('summary-refresh-button')).toBeEnabled();
    });
  });
});
