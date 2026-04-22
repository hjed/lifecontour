/**
 * Unit tests for ContactSummary component.
 */

import { render, screen } from '@testing-library/react';
import { ContactSummary } from '@/components/contacts/ContactSummary';
import { ContactSummaryResource, ContactSummaryStatus } from '@/types/contacts';

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
      is_user_override: false,
      user_override_text: null,
      generated_at: '2026-01-01T00:00:00Z',
      ...overrides,
    },
  };
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
        <ContactSummary
          summary={makeSummary({
            status: ContactSummaryStatus.DISABLED,
            is_disabled: true,
          })}
          contactId='1'
        />
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
          summary={makeSummary({
            status: ContactSummaryStatus.DISABLED,
            is_disabled: true,
            summary_text: null,
          })}
          contactId='1'
        />
      );

      expect(
        screen.getByText(/ai summary generation is disabled/i)
      ).toBeInTheDocument();
    });

    it('shows generating message when no text and not disabled', () => {
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

    it('disables refresh button when summary is disabled', () => {
      render(
        <ContactSummary
          summary={makeSummary({
            status: ContactSummaryStatus.DISABLED,
            is_disabled: true,
          })}
          contactId='1'
        />
      );

      expect(screen.getByTestId('summary-refresh-button')).toBeDisabled();
    });

    it('disables refresh button when component is disabled', () => {
      render(
        <ContactSummary summary={makeSummary()} contactId='1' disabled={true} />
      );

      expect(screen.getByTestId('summary-refresh-button')).toBeDisabled();
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
});
