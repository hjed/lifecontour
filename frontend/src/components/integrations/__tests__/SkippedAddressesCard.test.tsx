/** @jest-environment jsdom */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SkippedAddressesCard } from '../SkippedAddressesCard';
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

function issue(
  id: string,
  contactId: number,
  name: string
): ContactImportIssueResource {
  return {
    type: 'contact-import-issues',
    id,
    attributes: {
      contact_id: contactId,
      contact_name: name,
      integration_source: 'google',
      kind: 'skipped_address',
      reason: 'unrecognised_region',
      address: {
        street_line_1: '1 Rue de Rivoli',
        street_line_2: null,
        locality: null,
        region: 'Ile-de-France',
        postal_code: null,
        country_code: 'CA',
      },
      created_at: '2026-10-23T00:00:00Z',
    },
  };
}

describe('SkippedAddressesCard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useDismissContactImportIssue as jest.Mock).mockReturnValue({
      mutate: dismissMutate,
      isPending: false,
    });
  });

  it('is hidden when nothing was skipped', () => {
    (useContactImportIssues as jest.Mock).mockReturnValue({
      data: { data: [] },
    });

    const { container } = render(<SkippedAddressesCard />);

    expect(useContactImportIssues).toHaveBeenCalledWith();
    expect(container).toBeEmptyDOMElement();
  });

  it('lists every skipped address with a link to its contact', () => {
    (useContactImportIssues as jest.Mock).mockReturnValue({
      data: { data: [issue('3', 7, 'Kiri'), issue('4', 9, 'Ana')] },
    });

    render(<SkippedAddressesCard />);

    expect(screen.getByRole('link', { name: 'Kiri' })).toHaveAttribute(
      'href',
      '/contacts/7'
    );
    expect(screen.getByRole('link', { name: 'Ana' })).toHaveAttribute(
      'href',
      '/contacts/9'
    );
    expect(
      screen.getAllByText(
        '“Ile-de-France” isn’t a province or territory of Canada'
      )
    ).toHaveLength(2);
  });

  it('dismisses one', async () => {
    const user = userEvent.setup();
    (useContactImportIssues as jest.Mock).mockReturnValue({
      data: { data: [issue('3', 7, 'Kiri')] },
    });
    render(<SkippedAddressesCard />);

    await user.click(
      screen.getByRole('button', { name: 'Dismiss skipped address for Kiri' })
    );

    expect(dismissMutate).toHaveBeenCalledWith('3');
  });
});
