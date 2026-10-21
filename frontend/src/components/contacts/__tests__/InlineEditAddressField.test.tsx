/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InlineEditAddressField } from '../InlineEditAddressField';
import { PreconditionFailedError } from '@/lib/api/conditional-request';

const ADDRESS = {
  street_line_1: '1 George St',
  locality: 'Sydney',
  country_code: 'AU',
};

async function saveWith(onSave: jest.Mock) {
  render(
    <InlineEditAddressField
      value={ADDRESS}
      onSave={onSave}
      data-testid='address-field'
    />
  );
  await userEvent.click(screen.getByTestId('address-field'));
  await userEvent.click(screen.getByRole('button', { name: 'Save address' }));
  await waitFor(() => expect(onSave).toHaveBeenCalled());
}

describe('InlineEditAddressField save failures', () => {
  it('reopens with the error when a save fails', async () => {
    await saveWith(jest.fn().mockRejectedValue(new Error('Invalid postcode')));

    expect(await screen.findByText('Invalid postcode')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Save address' })
    ).toBeInTheDocument();
  });

  it('closes on a write conflict, which the conflict dialog reports', async () => {
    await saveWith(
      jest
        .fn()
        .mockRejectedValue(
          new PreconditionFailedError('moved on', 'PRECONDITION_FAILED', {})
        )
    );

    await waitFor(() =>
      expect(
        screen.queryByRole('button', { name: 'Save address' })
      ).not.toBeInTheDocument()
    );
    expect(screen.queryByText('moved on')).not.toBeInTheDocument();
  });
});

describe('InlineEditAddressField when the address changes while it is open', () => {
  it('asks before replacing an address that changed elsewhere since editing began', async () => {
    // A refetch brought another tab's postcode, and with it the newer tag:
    // saving the draft as-is would quietly restore the old one.
    const onSave = jest.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <InlineEditAddressField
        value={ADDRESS}
        onSave={onSave}
        data-testid='address-field'
      />
    );
    await userEvent.click(screen.getByTestId('address-field'));
    rerender(
      <InlineEditAddressField
        value={{ ...ADDRESS, postal_code: '2000' }}
        onSave={onSave}
        data-testid='address-field'
      />
    );

    await userEvent.click(screen.getByRole('button', { name: 'Save address' }));

    expect(onSave).not.toHaveBeenCalled();
    expect(
      await screen.findByText(
        'This address was changed elsewhere while you were editing. Save again to replace it.'
      )
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Save address' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  });
});
