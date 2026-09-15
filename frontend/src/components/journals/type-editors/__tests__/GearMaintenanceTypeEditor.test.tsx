/**
 * @jest-environment jsdom
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GearMaintenanceTypeEditor } from '../GearMaintenanceTypeEditor';
import { renderWithProviders } from '@/test-utils';
import * as gearItemsApi from '@/lib/api/gearItems';

jest.mock('@/lib/api/gearItems', () => ({
  getGearItems: jest.fn(),
  createGearItem: jest.fn(),
}));

const mockGetGearItems = gearItemsApi.getGearItems as jest.Mock;

describe('GearMaintenanceTypeEditor — maintenance types', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetGearItems.mockResolvedValue([]);
  });

  it('offers every maintenance type, including each Snipe-IT kind', async () => {
    const user = userEvent.setup();
    renderWithProviders(<GearMaintenanceTypeEditor createMode />);

    await user.click(await screen.findByLabelText('Maintenance Type'));

    const listbox = await screen.findByRole('listbox');
    const options = within(listbox)
      .getAllByRole('option')
      .map(option => option.textContent);
    expect(options).toEqual([
      'routine inspection',
      'routine maintenance',
      'repairing gear',
      'retiring gear',
      'upgrading gear',
      'calibration',
      'software support',
      'hardware support',
      'configuration change',
    ]);
  });
});
