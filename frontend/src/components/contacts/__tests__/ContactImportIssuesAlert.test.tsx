/** @jest-environment jsdom */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContactImportIssuesAlert } from '../ContactImportIssuesAlert';
import {
  useContactImportIssues,
  useDismissContactImportIssue,
} from '@/lib/api/contact-import-issues';
import type { ContactImportIssueResource } from '@/types/contact-import-issues';

jest.mock('@/lib/api/contact-import-issues', () => ({
  useContactImportIssues: jest.fn(),
  useDismissContactImportIssue: jest.fn(),
}));

const dismissMutate = jest.fn();

function issue(id: string): ContactImportIssueResource {
  return {
    type: 'contact-import-issues',
    id,
    attributes: {
      contact_id: 7,
      contact_name: 'Kiri Te Kanawa',
      integration_source: 'google',
      kind: 'skipped_address',
      reason: 'unrecognised_region',
      address: {
        street_line_1: '10 Downing St',
        street_line_2: null,
        locality: 'London',
        region: 'London',
        postal_code: 'SW1A 2AA',
        country_code: 'AU',
      },
      created_at: '2026-10-23T00:00:00Z',
    },
  };
}

function withIssues(issues: ContactImportIssueResource[]) {
  (useContactImportIssues as jest.Mock).mockReturnValue({
    data: { data: issues },
  });
}

describe('ContactImportIssuesAlert', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useDismissContactImportIssue as jest.Mock).mockReturnValue({
      mutate: dismissMutate,
      isPending: false,
    });
  });

  it('asks only for the contact’s own issues', () => {
    withIssues([]);

    render(<ContactImportIssuesAlert contactId='7' />);

    expect(useContactImportIssues).toHaveBeenCalledWith('7');
  });

  it('renders nothing when nothing was skipped', () => {
    withIssues([]);

    const { container } = render(<ContactImportIssuesAlert contactId='7' />);

    expect(container).toBeEmptyDOMElement();
  });

  it('explains a skipped address and how to fix it', () => {
    withIssues([issue('3')]);

    render(<ContactImportIssuesAlert contactId='7' />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('A Google address wasn’t imported');
    expect(alert).toHaveTextContent('10 Downing St, London, London SW1A 2AA');
    expect(alert).toHaveTextContent(
      '“London” isn’t a state or territory of Australia'
    );
    expect(alert).toHaveTextContent('Fix it in Google Contacts');
  });

  it('dismisses an issue', async () => {
    const user = userEvent.setup();
    withIssues([issue('3')]);
    render(<ContactImportIssuesAlert contactId='7' />);

    await user.click(screen.getByRole('button', { name: 'Dismiss' }));

    expect(dismissMutate).toHaveBeenCalledWith('3');
  });
});
