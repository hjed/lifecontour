import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TagContextMenu } from '../TagContextMenu';
import { TagResource } from '@/types/contacts';

// Mock TagManagementDialog because we're testing the ContextMenu interaction
jest.mock('../TagManagementDialog', () => ({
  TagManagementDialog: ({
    open,
    onOpenChange,
  }: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
  }) =>
    open ? (
      <div data-testid='mock-tag-dialog'>
        <button onClick={() => onOpenChange(false)}>Close Dialog</button>
      </div>
    ) : null,
}));

const mockTag: TagResource = {
  type: 'tags',
  id: '1',
  attributes: {
    name: 'Friend',
    color: '#ff0000',
    description: 'A close friend',
    created_at: '2023-01-01T00:00:00Z',
    updated_at: '2023-01-01T00:00:00Z',
  },
};

describe('TagContextMenu', () => {
  it('renders children correctly', () => {
    render(
      <TagContextMenu tag={mockTag}>
        <div data-testid='trigger'>Trigger Area</div>
      </TagContextMenu>
    );

    expect(screen.getByTestId('trigger')).toBeInTheDocument();
  });

  it('opens ContextMenu on right click and triggers edit dialog', async () => {
    render(
      <TagContextMenu tag={mockTag}>
        <div data-testid='trigger'>Trigger Area</div>
      </TagContextMenu>
    );

    const user = userEvent.setup();
    const trigger = screen.getByTestId('trigger');

    // Simulate right click to open context menu
    await user.pointer({ keys: '[MouseRight]', target: trigger });

    // Check if Edit Tag menu item appears
    const editMenuItem = await screen.findByRole('menuitem', {
      name: /Edit Tag/i,
    });
    expect(editMenuItem).toBeInTheDocument();

    // Click edit
    await user.click(editMenuItem);

    // Context menu should disappear (eventually) and dialog should appear
    expect(await screen.findByTestId('mock-tag-dialog')).toBeInTheDocument();

    // Close dialog
    await user.click(screen.getByRole('button', { name: /Close Dialog/i }));

    await waitFor(() => {
      expect(screen.queryByTestId('mock-tag-dialog')).not.toBeInTheDocument();
    });
  });
});
